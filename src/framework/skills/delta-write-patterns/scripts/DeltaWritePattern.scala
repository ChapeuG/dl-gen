package br.com.datalake.utils

import io.delta.tables.DeltaTable
import org.apache.spark.sql.{DataFrame, SaveMode, SparkSession}
import org.apache.spark.sql.expressions.Window
import org.apache.spark.sql.functions.{col, row_number}

/**
 * Padroes canonicos de escrita Delta Lake.
 *
 * Centraliza a logica de decisao entre overwrite (primeira carga)
 * e merge incremental (upsert), com deduplicacao pre-merge,
 * file sizing otimizado e geracao de manifesto para Athena.
 */
object DeltaWritePattern {

  /**
   * Deduplica o DataFrame mantendo apenas o registro mais recente por chave de merge.
   *
   * Usa Window + row_number para garantir, de forma deterministica, que o registro
   * com maior `timestampColumn` por chave seja mantido. O padrao orderBy + dropDuplicates
   * NAO oferece essa garantia: dropDuplicates re-particiona pelas chaves e descarta a
   * ordenacao global, mantendo um registro arbitrario por grupo.
   *
   * @param df              DataFrame de origem
   * @param mergeKeys       Colunas que formam a chave de merge
   * @param timestampColumn Coluna de timestamp para ordenacao (mais recente primeiro)
   * @return DataFrame deduplicado
   */
  def dedup(df: DataFrame, mergeKeys: Seq[String], timestampColumn: String): DataFrame = {
    val w = Window.partitionBy(mergeKeys.map(col): _*).orderBy(col(timestampColumn).desc)
    df.withColumn("__rn", row_number().over(w))
      .filter(col("__rn") === 1)
      .drop("__rn")
  }

  /**
   * Persiste DataFrame em Delta Lake com estrategia automatica:
   * - Primeira carga: overwrite com particionamento e file sizing
   * - Cargas subsequentes: merge incremental com condicoes null-safe
   *
   * @param spark           SparkSession ativa
   * @param df              DataFrame transformado e deduplicado
   * @param outputPath      Caminho de saida Delta
   * @param mergeConditions Map(source_col -> target_col) para condicao de merge
   * @param partitions      Colunas de particao
   * @param avgRowSize      Tamanho medio de uma linha em bytes (para calculo de maxRecordsPerFile)
   */
  def save(
    spark: SparkSession,
    df: DataFrame,
    outputPath: String,
    mergeConditions: Map[String, String],
    partitions: Seq[String],
    avgRowSize: Int = 340
  ): Unit = {

    val isDelta = DeltaTable.isDeltaTable(outputPath)

    // Adaptive file sizing para overwrite e MERGE — evita small files sem risco de OOM em particoes grandes
    spark.conf.set("spark.databricks.delta.optimizeWrite.enabled", "true")

    if (isDelta) {
      // Configs de otimizacao para merge
      spark.conf.set("spark.databricks.delta.merge.optimizeInsertOnlyMerge.enabled", "true")
      spark.conf.set("spark.databricks.delta.merge.repartitionBeforeWrite.enabled", "true")
      spark.conf.set("spark.databricks.delta.schema.autoMerge.enabled", "true")

      // Condicao null-safe com <=>
      val conditions = mergeConditions
        .map { case (src, tgt) => s"s.$src <=> t.$tgt" }
        .mkString(" and ")

      val updateAssignments: Map[String, org.apache.spark.sql.Column] =
        df.columns
          .filterNot(_ == "dh_criacao_registro")
          .map(c => c -> col(s"s.$c"))
          .toMap

      DeltaTable.forPath(outputPath).alias("t")
        .merge(df.alias("s"), conditions)
        .whenMatched().update(updateAssignments)
        .whenNotMatched().insertAll()
        .execute()
    } else {
      // Primeira carga: overwrite com file sizing
      val nrRows: Long = (128 * 1024 * 1024) / avgRowSize

      df.write
        .mode(SaveMode.Overwrite)
        .format("delta")
        .option("delta.autoOptimize.optimizeWrite", "true")
        .option("maxRecordsPerFile", nrRows)
        .partitionBy(partitions: _*)
        .save(outputPath)
    }

    // Gerar manifesto para Athena
    DeltaTable.forPath(outputPath).generate("symlink_format_manifest")
  }
}

package br.com.datalake.utils

import org.apache.spark.sql.DataFrame
import org.apache.spark.sql.functions.{broadcast, col, lit}

/**
 * Helper para joins de enriquecimento com broadcast.
 *
 * Encapsula o padrao de leitura de tabela Delta de dimensao,
 * broadcast, aliasing sequencial e join com o DataFrame principal.
 */
object ApplyEnrichment {

  /**
   * Aplica um join de enriquecimento com broadcast no DataFrame principal.
   *
   * @param df         DataFrame principal (fato)
   * @param enrichment Definicao do enrichment (trait Enrichment)
   * @param s3Path     Caminho base S3 para construir o path da tabela lookup
   * @param seq        Contador sequencial para alias unico (delta1, delta2, ...)
   * @return DataFrame enriquecido com as colunas do lookup
   */
  def applyEnrichment(df: DataFrame, enrichment: Enrichment, s3Path: String, seq: Int): DataFrame = {
    if (!enrichment.isActive) return df

    // 1. Construir path e selecionar apenas colunas necessarias (early projection)
    val lookupPath = FileUtils.getS3PathToDeltaTable(s3Path, enrichment.team, enrichment.dataset, enrichment.table)
    val selectCols = (
      enrichment.lookupColumnList ++
      enrichment.lookupJoinConditions.keys ++
      enrichment.lookupFixedConditions.keys ++
      enrichment.lookupConditionalConditions.keys
    ).distinct

    // 2. Broadcast: forca broadcast hash join para tabelas pequenas
    val lookupDf = broadcast(
      df.sparkSession.read.format("delta").load(lookupPath)
        .select(selectCols.map(col): _*)
    )

    // 3. Aliasing: prefixo sequencial para evitar ambiguidade
    val applyAlias = (column: String) => s"delta${seq}_$column"

    // Renomear colunas de resultado (aliases definidos no enrichment)
    val columnsToRename = enrichment.lookupColumnAliasList -- enrichment.lookupJoinConditions.keys.toSet
    // Renomear chaves de join com prefixo interno
    val allJoinKeys = enrichment.lookupJoinConditions.keys ++
      enrichment.lookupFixedConditions.keys ++
      enrichment.lookupConditionalConditions.keys
    val keysToRename = allJoinKeys
      .foldLeft(Map[String, String]())((out, c) => out + (c -> applyAlias(c)))
    val renamedLookup = DataFrameUtils.renameColumns(lookupDf, columnsToRename ++ keysToRename)

    // 4. Construir condicao de join
    val normalConditions = enrichment.lookupJoinConditions
      .map { case (lookupCol, dfCol) => col(s"delta$seq.${applyAlias(lookupCol)}") === col(s"dataframe.$dfCol") }
    val fixedConditions = enrichment.lookupFixedConditions
      .map { case (lookupCol, fixedVal) => col(s"delta$seq.${applyAlias(lookupCol)}") === lit(fixedVal) }
    val conditionalConditions = enrichment.lookupConditionalConditions
      .map { case (lookupCol, expr) => col(s"delta$seq.${applyAlias(lookupCol)}") === expr }
    val conditions = (normalConditions ++ fixedConditions ++ conditionalConditions).reduce(_ and _)

    // 5. Executar join
    var result = df.alias("dataframe")
      .join(renamedLookup.alias(s"delta$seq"), conditions, enrichment.lookupJoinType)

    // 6. Renomear ou remover chaves temporarias
    val renameKeys = allJoinKeys
      .foldLeft(Map[String, String]())((out, key) =>
        out + (applyAlias(key) -> enrichment.lookupColumnAliasList.getOrElse(key, applyAlias(key))))
    result = DataFrameUtils.renameColumns(result, renameKeys)
    result.drop(keysToRename.values.toList: _*)
  }

  /**
   * Aplica uma sequencia de enrichments sobre o DataFrame.
   *
   * @param df      DataFrame principal
   * @param joinSeq Sequencia de Enrichment a aplicar
   * @param s3Path  Caminho base S3
   * @return DataFrame com todos os enrichments aplicados
   */
  def applyAll(df: DataFrame, joinSeq: Seq[Enrichment], s3Path: String): DataFrame = {
    var enrichedDf = df
    var seq = 1
    joinSeq.foreach { enrichment =>
      enrichedDf = applyEnrichment(enrichedDf, enrichment, s3Path, seq)
      if (enrichment.isActive) seq += 1
    }
    enrichedDf
  }
}

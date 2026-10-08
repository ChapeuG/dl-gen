package br.com.datalake.utils

import org.apache.spark.sql.{Column, DataFrame, SparkSession}
import org.apache.spark.sql.functions.col

/**
 * Executa LEFT JOIN entre o fato principal e uma tabela fato complementar,
 * aplicando filtro de particao para pruning e renames opcionais do lado
 * complementar antes do join. Semantica equivalente a um RIGHT JOIN feito
 * a partir do complemento preservando todos os registros da main.
 */
object FactRightJoin {

  /** Colunas de sistema do lado complementar que sempre conflitam com o main
   *  (traceability + particoes). Sao removidas antes do join para evitar
   *  duplicacao de nomes apos o left_outer com chaves via Seq[String]. */
  private val systemColumnsToDrop: Seq[String] = Seq(
    "dh_criacao_registro",
    "dh_atualizacao_registro",
    "dt_atualizacao_registro_particao",
    "dt_local_transacao_bit13_particao",
    "dh_criacao_data_lake"
  )

  def apply(
    main: DataFrame,
    complementPath: String,
    joinKeys: Seq[String],
    renames: Map[String, String],
    partitionDate: Column,
    extraDropsFromComplement: Seq[String] = Seq.empty,
    partitionColumn: String = "dt_atualizacao_registro_particao"
  )(implicit spark: SparkSession): DataFrame = {
    val complementRaw = spark.read.format("delta").load(complementPath)
      .filter(col(partitionColumn) === partitionDate)

    val allDrops = (systemColumnsToDrop ++ extraDropsFromComplement).distinct
    val dropCols = allDrops.filter(complementRaw.columns.contains)
    val complementCleaned = complementRaw.drop(dropCols: _*)

    val complementRenamed = DataFrameUtils.renameColumns(complementCleaned, renames)
    main.join(complementRenamed, joinKeys, "left_outer")
  }
}

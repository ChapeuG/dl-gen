package br.com.datalake.utils

import org.apache.spark.sql.DataFrame
import org.apache.spark.sql.functions.{col, lit, substring}

import java.sql.Timestamp

/**
 * Utilitarios de DataFrame usados pelos processors: rename raw -> staging,
 * extracao de subcampos posicionais e campos de rastreabilidade.
 */
object DataFrameUtils {

  /**
   * Renomeia colunas conforme o mapa `origem -> destino` em um unico `select`.
   * Colunas fora do mapa sao mantidas com o nome original.
   */
  def renameColumns(df: DataFrame, renameMap: Map[String, String]): DataFrame =
    df.select(df.columns.map(c => col(s"`$c`").as(renameMap.getOrElse(c, c))): _*)

  /**
   * Extrai subcampos posicionais (1-based) como string. A tipagem acontece
   * depois, no `select` unico de transformacao (ver catalyst-optimization).
   */
  def substringExtract(df: DataFrame, nestedSpecs: Seq[NestedFieldSpec]): DataFrame =
    nestedSpecs.foldLeft(df) { case (currentDf, spec) =>
      currentDf.withColumn(spec.targetName, substring(col(spec.parentColumn), spec.startPos, spec.length))
    }

  /**
   * Carimba os campos de rastreabilidade com o run timestamp resolvido no driver.
   * No MERGE, `dh_criacao_registro` e preservado (ver delta-write-patterns).
   */
  def addTraceabilityFields(df: DataFrame, runTimestamp: Timestamp): DataFrame = {
    val ts = lit(runTimestamp)
    df.withColumn("dh_criacao_registro", ts)
      .withColumn("dh_atualizacao_registro", ts)
  }
}

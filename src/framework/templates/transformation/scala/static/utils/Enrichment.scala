package br.com.datalake.utils

import org.apache.spark.sql.Column

/**
 * Contrato de um join de enriquecimento com tabela de dimensao (ver enrichment-joins).
 */
trait Enrichment {
  val team: String
  val dataset: String
  val table: String
  val lookupColumnList: List[String]
  val lookupColumnAliasList: Map[String, String]
  val lookupJoinConditions: Map[String, String]
  val lookupFixedConditions: Map[String, String] = Map.empty
  val lookupConditionalConditions: Map[String, Column] = Map.empty
  val lookupJoinType: String
  val isActive: Boolean
}

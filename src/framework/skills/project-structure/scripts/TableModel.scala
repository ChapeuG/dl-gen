package br.com.datalake.utils

/**
 * Contrato que toda definicao de tabela deve satisfazer.
 *
 * E um objeto de configuracao puro — sem SparkContext, sem I/O.
 * O Processor depende apenas desta trait, garantindo que novos
 * processamentos possam ser adicionados sem alterar codigo compartilhado.
 */
trait TableModel {

  /** Nome da tabela Delta no metastore. */
  def tableName: String

  /** Nome do database/schema no metastore. */
  def databaseName: String

  /** Comentario da tabela (truncado em 255 chars no DDL). */
  def tableComment: String

  /** Lista ordenada de especificacoes de campos diretos. */
  def fields: Seq[FieldSpec]

  /** Especificacoes de subcampos extraidos via substring (ex: BIT63). Vazio se nao ha nested fields. */
  def nestedFields: Seq[NestedFieldSpec]

  /** Nomes das colunas usadas como chave de merge ao salvar em Delta. */
  def mergeKeys: Seq[String]

  /** Nomes das colunas de particao, na ordem dos niveis. */
  def partitionColumns: Seq[String]

  /** Coluna de timestamp usada para ordenacao na deduplicacao (mais recente primeiro). */
  def timestampField: String

  /** Sequencia de enrichments a aplicar. Vazio se nao ha enriquecimentos. */
  def enrichments: Seq[Enrichment]

  /** Mapa de comentarios por coluna (targetName -> comentario). */
  def columnComments: Map[String, String]

  /** Nomes das colunas de origem — usados para selecionar colunas ao ler a fonte. */
  final def sourceSchema: Seq[String] = fields.map(_.sourceName)

  /** Mapa de rename: sourceName -> targetName. */
  final def rawToStagingMap: Map[String, String] = fields.map(f => f.sourceName -> f.targetName).toMap

  /** Nome completo qualificado `database.tabela`. */
  final def fullTableName: String = s"$databaseName.$tableName"
}

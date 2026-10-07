package br.com.datalake.utils

import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.sql.types._

/**
 * Gerenciamento de tabelas Hive/Athena externas para Delta Lake.
 *
 * Cobre criacao de tabela com symlink manifest, mapeamento de tipos
 * Spark->Hive, schema evolution e registro incremental de particoes.
 *
 * Substitui o uso de `MSCK REPAIR TABLE` por operacoes diretas e incrementais.
 */
object HiveTableManager {

  /**
   * Mapeia DataType do Spark para tipo Hive equivalente.
   */
  def sparkToHiveType(dt: DataType): String = dt match {
    case StringType      => "string"
    case IntegerType     => "int"
    case LongType        => "bigint"
    case DoubleType      => "double"
    case FloatType       => "float"
    case BooleanType     => "boolean"
    case DateType        => "date"
    case TimestampType   => "timestamp"
    case d: DecimalType  => s"decimal(${d.precision},${d.scale})"
    case BinaryType      => "binary"
    case _               => "string"
  }

  /**
   * Gera fragmento DDL de comentario para coluna, truncando em 255 caracteres.
   */
  def getColumnComment(fieldName: String, columnComments: Map[String, String]): String = {
    columnComments.getOrElse(fieldName, "") match {
      case c if c.nonEmpty && c.length <= 255 => s""" COMMENT "$c""""
      case c if c.nonEmpty                    => s""" COMMENT "${c.substring(0, 255)}""""
      case _                                  => ""
    }
  }

  /**
   * Cria tabela externa Hive apontando para o manifesto symlink do Delta.
   *
   * @param spark          SparkSession ativa
   * @param tableName      Nome completo da tabela (database.table)
   * @param schema         Schema do DataFrame (inclui todas as colunas)
   * @param partitions     Nomes das colunas de particao
   * @param outputPath     Caminho raiz da tabela Delta
   * @param tableComment   Comentario da tabela (truncado em 255 chars)
   * @param columnComments Map com comentarios por coluna
   * @param database       Nome do database Hive
   */
  def createTable(
                   spark: SparkSession,
                   tableName: String,
                   schema: StructType,
                   partitions: Seq[String],
                   outputPath: String,
                   tableComment: String = "",
                   columnComments: Map[String, String] = Map(),
                   database: String = ""
                 ): Unit = {

    if (database.nonEmpty) spark.sql(s"use $database")

    val partitionColSet = partitions.toSet
    val nonPartFields = schema.fields.filter(f => !partitionColSet.contains(f.name))
    val partFields = schema.fields.filter(f => partitionColSet.contains(f.name))

    val columnsDDL = nonPartFields
      .map(f => s"`${f.name.replace(".", "_")}` ${sparkToHiveType(f.dataType)}${getColumnComment(f.name, columnComments)}")
      .mkString(",\n    ")
    val partitionDDL = partFields
      .map(f => s"`${f.name.replace(".", "_")}` ${sparkToHiveType(f.dataType)}${getColumnComment(f.name, columnComments)}")
      .mkString(", ")

    val manifestPath = outputPath + "/_symlink_format_manifest/"
    val tableCommentDDL = if (tableComment.nonEmpty && tableComment.length <= 255) s"COMMENT '$tableComment'"
    else if (tableComment.nonEmpty) s"COMMENT '${tableComment.substring(0, 255)}'"
    else ""

    spark.sql(
      s"""CREATE EXTERNAL TABLE IF NOT EXISTS $tableName (
         |    $columnsDDL
         |)
         |$tableCommentDDL
         |PARTITIONED BY ($partitionDDL)
         |ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
         |STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.SymlinkTextInputFormat'
         |  OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
         |LOCATION '$manifestPath'""".stripMargin)
  }

  /**
   * Detecta colunas novas no schema e adiciona via ALTER TABLE.
   *
   * @param spark          SparkSession ativa
   * @param tableName      Nome da tabela existente
   * @param schemaFields   Campos do schema atual (excluindo particoes)
   * @param columnComments Map com comentarios por coluna
   */
  def evolveSchema(
                    spark: SparkSession,
                    tableName: String,
                    schemaFields: Array[StructField],
                    columnComments: Map[String, String] = Map()
                  ): Unit = {
    val existingCols = spark.catalog.listColumns(tableName).collect().map(_.name).toSet
    val newColumns = schemaFields.filter(f => !existingCols.contains(f.name))
    val columnDDLs = newColumns
      .map(field => s"`${field.name.replace(".", "_")}` ${sparkToHiveType(field.dataType)}${getColumnComment(field.name, columnComments)}")
    columnDDLs.foreach { columnDDL =>
      spark.sql(
        s"""ALTER TABLE $tableName ADD COLUMNS (
           |    $columnDDL
           |)""".stripMargin)
    }
  }

  /**
   * Tamanho maximo de particoes por statement ALTER TABLE ADD PARTITION.
   * Evita estourar limites de tamanho de query no metastore (Glue/Hive).
   */
  private val PARTITION_BATCH_SIZE = 100

  /**
   * Registra particoes do batch atual via ALTER TABLE ADD PARTITION em lote.
   * Substitui MSCK REPAIR TABLE que escaneia todas as particoes existentes.
   *
   * Generalizado para aceitar qualquer numero de niveis de particao (1, 2, ou mais).
   *
   * @param spark           SparkSession ativa
   * @param tableName       Nome da tabela
   * @param df              DataFrame com dados do batch (para extrair valores de particao)
   * @param partitionFields Nomes das colunas de particao (em ordem dos niveis)
   */
  def registerPartitions(
                          spark: SparkSession,
                          tableName: String,
                          df: DataFrame,
                          partitionFields: Seq[String]
                        ): Unit = {
    val partitionValues = df
      .select(partitionFields.head, partitionFields.tail: _*)
      .distinct()
      .collect()

    partitionValues.grouped(PARTITION_BATCH_SIZE).foreach { batch =>
      val partitionClauses = batch.map { row =>
        val kvPairs = partitionFields.zipWithIndex.map { case (fieldName, idx) =>
          s"$fieldName='${row.getString(idx)}'"
        }.mkString(", ")
        s"PARTITION ($kvPairs)"
      }.mkString("\n    ")

      spark.sql(
        s"""ALTER TABLE $tableName ADD IF NOT EXISTS
           |    $partitionClauses""".stripMargin)
    }
  }
}

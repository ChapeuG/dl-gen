package br.com.datalake.utils

import org.apache.spark.sql.types.DataType

/**
 * Descreve a transformacao de um unico campo entre a fonte de dados e a tabela Delta destino.
 *
 * E a unidade atomica que conecta o schema de leitura ao schema final persistido.
 *
 * @param sourceName     Nome da coluna no arquivo de origem (rawField).
 * @param targetName     Nome da coluna apos rename na tabela Delta destino (stagingField).
 * @param targetType     Tipo Spark final da coluna (ex: `IntegerType`, `StringType`).
 * @param comment        Texto descritivo armazenado como metadata da coluna.
 * @param encrypted      Se `true`, o valor recebe TRIM e e criptografado com AES-128.
 * @param sourceFormat   Padrao de parsing para DateType ou TimestampType (ex: `"yyyyMMdd"`).
 * @param transformation Tipo de transformacao a aplicar:
 *                       - `Some("default")`: transformacao padrao por tipo (TRIM+UPPER para String, cast para numericos, normalizeTimestamp para Timestamp).
 *                       - `Some("format")`: parsing com formato customizado (usa sourceFormat).
 *                       - `None`: sem transformacao (preservar valor original).
 */
final case class FieldSpec(
  sourceName:     String,
  targetName:     String,
  targetType:     DataType,
  comment:        String,
  encrypted:      Boolean        = false,
  sourceFormat:   Option[String] = None,
  transformation: Option[String] = None
)

package br.com.datalake.utils

import org.apache.spark.sql.Column
import org.apache.spark.sql.functions.{col, to_date, to_timestamp, trim, upper, when}
import org.apache.spark.sql.types._

/**
 * Dispatch de transformacao de colunas baseado em pattern matching sobre
 * (dataType, transformation) conforme definido no FieldSpec.
 *
 * Usado dentro de um unico `.select()` para gerar 1 Project node no Catalyst,
 * em vez de N nodes gerados por `.withColumn()` encadeados.
 */
object TransformColumn {

  /**
   * Retorna a expressao Column transformada conforme o FieldSpec.
   *
   * Regras de dispatch:
   * - transformation = None (null no SDD): preservar valor sem transformacao
   * - transformation = "default": aplicar transformacao padrao por tipo
   * - transformation = "format": parsing com formato customizado (sourceFormat)
   */
  def apply(f: FieldSpec): Column = (f.targetType, f.transformation) match {

    // === Sem transformacao (null no SDD) — preservar valor original ===
    case (_, None) => col(f.targetName)

    // === StringType default: TRIM + UPPER ===
    case (StringType, Some("default")) => trim(upper(col(f.targetName)))

    // === Tipos numericos default: cast ===
    case (IntegerType, Some("default")) => col(f.targetName).cast(IntegerType)
    case (LongType, Some("default"))    => col(f.targetName).cast(LongType)

    // === DecimalType default: cast ===
    case (dt, Some("default")) if dt.simpleString.contains("decimal") =>
      col(f.targetName).cast(f.targetType)

    // === DateType default: to_date ===
    case (DateType, Some("default")) => to_date(col(f.targetName))

    // === DateType com formato: to_date com pattern ===
    case (DateType, Some("format")) =>
      to_date(col(f.targetName), f.sourceFormat.get)

    // === TimestampType default: normalizeTimestampString + to_timestamp ===
    case (TimestampType, Some("default")) =>
      to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)))

    // === TimestampType com formato: normalizeTimestampString + to_timestamp com pattern ===
    case (TimestampType, Some("format")) =>
      to_timestamp(NormalizeTimestamp.normalizeTimestampString(col(f.targetName)), f.sourceFormat.get)

    // === BooleanType default: S/N -> true/false ===
    case (BooleanType, Some("default")) =>
      when(col(f.targetName).isin("s", "S", "true"), value = true)
        .when(col(f.targetName).isin("n", "N", "false"), value = false)

    // === [framework] Demais numericos default: cast (a raw e lida como StringType) ===
    case (dt @ (ShortType | ByteType | DoubleType | FloatType), Some("default")) =>
      col(f.targetName).cast(dt)

    // === [framework] Valor monetario em centavos na origem: cast / 100 ===
    case (dt, Some("centavos")) =>
      (col(f.targetName).cast(DecimalType(38, 0)) / 100).cast(dt)

    // === Fallback: retorna coluna sem transformacao ===
    case _ => col(f.targetName)
  }
}

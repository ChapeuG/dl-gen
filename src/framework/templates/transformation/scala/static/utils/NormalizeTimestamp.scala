package br.com.datalake.utils

import org.apache.spark.sql.expressions.UserDefinedFunction
import org.apache.spark.sql.functions.udf

/**
 * UDF para normalizacao de strings de timestamp antes da conversao
 * para TimestampType via `to_timestamp`.
 *
 * Trata inconsistencias comuns em dados brutos:
 * - Espacos extras entre data e hora
 * - Ausencia do separador "T" (ISO 8601)
 * - Uso de "/" ao inves de "-" como separador de data
 *
 * Nao altera o valor temporal — apenas normaliza o formato
 * para que `to_timestamp` consiga parsear corretamente.
 */
object NormalizeTimestamp {

  /**
   * UDF que normaliza uma string de timestamp para formato ISO 8601 compativel.
   *
   * Transformacoes aplicadas:
   * 1. Remove todos os espacos
   * 2. Insere "T" entre data e hora se ausente (para strings >= 18 chars)
   * 3. Substitui "/" por "-" no separador de data
   *
   * Retorna o valor original se:
   * - A string for null
   * - A string tiver menos de 18 caracteres (formato curto, sem hora completa)
   * - Ocorrer qualquer excecao durante o processamento
   *
   * Uso:
   * {{{
   *   import org.apache.spark.sql.functions.{col, to_timestamp}
   *
   *   // Aplicar normalizacao antes de to_timestamp
   *   df.withColumn("ts", to_timestamp(normalizeTimestampString(col("raw_ts"))))
   *
   *   // Com formato customizado
   *   df.withColumn("ts", to_timestamp(normalizeTimestampString(col("raw_ts")), "yyyy-MM-dd'T'HH:mm:ss"))
   * }}}
   */
  val normalizeTimestampString: UserDefinedFunction = udf { (value: String) =>
    try {
      if (value == null) null
      else {
        val trimmed = value.replace(" ", "")
        if (trimmed.length >= 18) {
          val upper = trimmed.toUpperCase
          val withT = if (upper.indexOf("T") == -1)
            upper.substring(0, 10) + "T" + upper.substring(10)
          else upper
          withT.replace("/", "-")
        } else value
      }
    } catch {
      case _: Exception => value
    }
  }
}

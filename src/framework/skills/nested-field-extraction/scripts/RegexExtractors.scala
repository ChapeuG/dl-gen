package br.com.datalake.utils

import org.apache.spark.sql.expressions.UserDefinedFunction
import org.apache.spark.sql.functions.udf

/**
 * UDFs de extracao por regex sobre o BIT48 (dc_informacao_adicional_transacao_bit48).
 *
 * O BIT48 contem blocos identificados por marcadores:
 *   *PRDnnn<valor>   — Codigo do Produto
 *   *VPSnnnF<NN...>  — Parcelamento (tipo de financiamento + parcelas)
 *
 * Em ambos, `nnn` sao 3 digitos que informam o tamanho do valor que segue.
 */
object RegexExtractors {

  private val prdPattern = """\*PRD(\d{3})(\d+)""".r
  private val vpsPattern = """\*VPS(\d{3})(\d)(\d*)""".r

  /** Extrai o Codigo do Produto do BIT48. Retorna null se nao houver padrao PRD valido. */
  val applyPrdRegex: UserDefinedFunction = udf { (value: String) =>
    if (value == null) null
    else prdPattern.findFirstMatchIn(value) match {
      case Some(m) =>
        val len = m.group(1).toInt
        val raw = m.group(2)
        if (raw.length >= len) raw.substring(0, len) else null
      case None => null
    }
  }

  /**
   * Extrai a quantidade de parcelas do bloco VPS do BIT48.
   *
   * Regras de tamanho (do SDD pedido_parceiro, secao 6):
   *   - tamanho >= 3: extrai 2 digitos de parcelas
   *   - tamanho == 2: extrai 1 digito de parcelas
   *   - tamanho == 1: retorna null (apenas tipo de financiamento presente)
   */
  val applyVpsRegex: UserDefinedFunction = udf { (value: String) =>
    if (value == null) null
    else vpsPattern.findFirstMatchIn(value) match {
      case Some(m) =>
        val len = m.group(1).toInt
        val digits = m.group(3)
        len match {
          case 1                                   => null
          case 2 if digits.length >= 1             => digits.substring(0, 1)
          case n if n >= 3 && digits.length >= 2   => digits.substring(0, 2)
          case _                                   => null
        }
      case None => null
    }
  }
}

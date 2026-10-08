package br.com.datalake.utils

import org.apache.spark.sql.types.DataType

/**
 * Especificacao de um subcampo extraido via substring de um campo posicional (NestedField).
 *
 * Modela campos ISO 8583 onde um unico BIT contem multiplos subcampos em posicoes fixas
 * (ex: BIT63 com enderecos de cobranca e entrega em posicoes 1-547).
 *
 * @param parentColumn Nome da coluna pai (stagingField) de onde o substring sera extraido.
 * @param targetName   Nome da coluna destino apos extracao.
 * @param startPos     Posicao inicial (1-based) para o substring.
 * @param length       Tamanho do substring a extrair.
 * @param targetType   Tipo Spark da coluna extraida.
 * @param comment      Texto descritivo do subcampo.
 */
final case class NestedFieldSpec(
  parentColumn:   String,
  targetName:     String,
  startPos:       Int,
  length:         Int,
  targetType:     DataType,
  comment:        String,
  transformation: Option[String] = None
)

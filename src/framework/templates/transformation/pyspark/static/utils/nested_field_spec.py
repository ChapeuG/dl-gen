"""Especificacao de um subcampo extraido via substring de um campo posicional."""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql.types import DataType


@dataclass(frozen=True)
class NestedFieldSpec:
    """Subcampo extraido via substring de um campo posicional (NestedField).

    Modela campos ISO 8583 onde um unico BIT contem multiplos subcampos em posicoes fixas
    (ex: BIT63 com enderecos de cobranca e entrega em posicoes 1-547).

    Atributos:
        parent_column: Nome da coluna pai (stagingField) de onde o substring sera extraido.
        target_name:   Nome da coluna destino apos extracao.
        start_pos:     Posicao inicial (1-based) para o substring.
        length:        Tamanho do substring a extrair.
        target_type:   Tipo Spark da coluna extraida.
        comment:       Texto descritivo do subcampo.
    """

    parent_column: str
    target_name: str
    start_pos: int
    length: int
    target_type: DataType
    comment: str
    transformation: str | None = None

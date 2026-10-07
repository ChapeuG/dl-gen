"""Especificacao de um campo entre a fonte de dados e a tabela Delta destino."""

from __future__ import annotations

from dataclasses import dataclass

from pyspark.sql.types import DataType


@dataclass(frozen=True)
class FieldSpec:
    """Descreve a transformacao de um unico campo entre a fonte de dados e a tabela Delta destino.

    E a unidade atomica que conecta o schema de leitura ao schema final persistido.

    Atributos:
        source_name:    Nome da coluna no arquivo de origem (rawField).
        target_name:    Nome da coluna apos rename na tabela Delta destino (stagingField).
        target_type:    Tipo Spark final da coluna (ex: ``IntegerType()``, ``StringType()``).
        comment:        Texto descritivo armazenado como metadata da coluna.
        encrypted:      Se ``True``, o valor chega criptografado (AES/ECB + base64) da ingestao.
        source_format:  Padrao de parsing para DateType ou TimestampType (ex: ``"yyyyMMdd"``).
        transformation: Tipo de transformacao a aplicar:
                        - ``"default"``: transformacao padrao por tipo (TRIM+UPPER para String,
                          cast para numericos, normalize_timestamp para Timestamp).
                        - ``"format"``: parsing com formato customizado (usa source_format).
                        - ``"centavos"``: valor monetario em centavos na origem (cast / 100).
                        - ``None``: sem transformacao (preservar valor original).
    """

    source_name: str
    target_name: str
    target_type: DataType
    comment: str
    encrypted: bool = False
    source_format: str | None = None
    transformation: str | None = None

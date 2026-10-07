"""Dispatch de transformacao de colunas sobre (data_type, transformation) do FieldSpec.

Usado dentro de um unico ``.select()`` para gerar 1 Project node no Catalyst,
em vez de N nodes gerados por ``.withColumn()`` encadeados.
"""

from __future__ import annotations

from pyspark.sql import Column
from pyspark.sql.functions import col, to_date, to_timestamp, trim, upper, when
from pyspark.sql.types import (BooleanType, ByteType, DateType, DecimalType, DoubleType, FloatType, IntegerType,
                               LongType, ShortType, StringType, TimestampType)

from datalake.utils.field_spec import FieldSpec
from datalake.utils.normalize_timestamp import normalize_timestamp_string

_NUMERIC = (IntegerType, LongType, ShortType, ByteType, DoubleType, FloatType, DecimalType)


def transform_column(f: FieldSpec) -> Column:
    """Expressao Column transformada conforme o FieldSpec.

    Regras de dispatch:
    - transformation = None (null no SDD): preservar valor sem transformacao
    - transformation = "default": transformacao padrao por tipo
    - transformation = "format": parsing com formato customizado (source_format)
    - transformation = "centavos": valor monetario em centavos na origem (cast / 100)
    """
    c = col(f.target_name)
    dt = f.target_type
    t = f.transformation

    # Sem transformacao (null no SDD) — preservar valor original
    if t is None:
        return c

    # Valor monetario em centavos na origem: cast / 100
    if t == "centavos":
        return (c.cast(DecimalType(38, 0)) / 100).cast(dt)

    if t == "default":
        # StringType: TRIM + UPPER
        if isinstance(dt, StringType):
            return trim(upper(c))
        # Numericos e decimais: cast (a raw e lida como StringType)
        if isinstance(dt, _NUMERIC):
            return c.cast(dt)
        # DateType: to_date
        if isinstance(dt, DateType):
            return to_date(c)
        # TimestampType: normalize_timestamp_string + to_timestamp
        if isinstance(dt, TimestampType):
            return to_timestamp(normalize_timestamp_string(c))
        # BooleanType: S/N -> true/false
        if isinstance(dt, BooleanType):
            return when(c.isin("s", "S", "true"), True).when(c.isin("n", "N", "false"), False)

    if t == "format":
        if isinstance(dt, DateType):
            return to_date(c, f.source_format)
        if isinstance(dt, TimestampType):
            return to_timestamp(normalize_timestamp_string(c), f.source_format)

    # Fallback: retorna coluna sem transformacao
    return c

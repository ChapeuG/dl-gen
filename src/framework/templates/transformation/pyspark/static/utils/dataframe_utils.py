"""Utilitarios de DataFrame usados pelos processors: rename raw -> staging,
extracao de subcampos posicionais e campos de rastreabilidade."""

from __future__ import annotations

from datetime import datetime

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, lit, substring

from datalake.utils.nested_field_spec import NestedFieldSpec


def rename_columns(df: DataFrame, rename_map: dict[str, str]) -> DataFrame:
    """Renomeia colunas conforme o mapa ``origem -> destino`` em um unico ``select``.
    Colunas fora do mapa sao mantidas com o nome original."""
    return df.select([col(f"`{c}`").alias(rename_map.get(c, c)) for c in df.columns])


def substring_extract(df: DataFrame, nested_specs: list[NestedFieldSpec]) -> DataFrame:
    """Extrai subcampos posicionais (1-based) como string. A tipagem acontece
    depois, no ``select`` unico de transformacao (ver catalyst-optimization)."""
    for spec in nested_specs:
        df = df.withColumn(spec.target_name, substring(col(spec.parent_column), spec.start_pos, spec.length))
    return df


def add_traceability_fields(df: DataFrame, run_timestamp: datetime) -> DataFrame:
    """Carimba os campos de rastreabilidade com o run timestamp resolvido no driver.
    No MERGE, ``dh_criacao_registro`` e preservado (ver delta-write-patterns)."""
    ts = lit(run_timestamp)
    return df.withColumn("dh_criacao_registro", ts).withColumn("dh_atualizacao_registro", ts)

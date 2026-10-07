"""Contrato de um join de enriquecimento com tabela de dimensao (ver enrichment-joins)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pyspark.sql import Column


@dataclass(frozen=True)
class Enrichment:
    team: str
    dataset: str
    table: str
    lookup_column_list: list[str]
    lookup_column_alias_list: dict[str, str]
    lookup_join_conditions: dict[str, str]
    lookup_join_type: str
    is_active: bool
    lookup_fixed_conditions: dict[str, str] = field(default_factory=dict)
    lookup_conditional_conditions: dict[str, Column] = field(default_factory=dict)

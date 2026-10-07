"""Contrato que toda definicao de tabela deve satisfazer."""

from __future__ import annotations

from datalake.utils.enrichment import Enrichment
from datalake.utils.field_spec import FieldSpec
from datalake.utils.nested_field_spec import NestedFieldSpec


class TableModel:
    """Objeto de configuracao puro — sem SparkSession, sem I/O.

    O processor depende apenas desta classe, garantindo que novos processamentos
    possam ser adicionados sem alterar codigo compartilhado. Cada tabela declara
    uma subclasse com os atributos abaixo.
    """

    #: Nome da tabela Delta no metastore.
    table_name: str
    #: Nome do database/schema no metastore.
    database_name: str
    #: Comentario da tabela (truncado em 255 chars no DDL).
    table_comment: str
    #: Lista ordenada de especificacoes de campos diretos.
    fields: list[FieldSpec]
    #: Subcampos extraidos via substring (ex: BIT63). Vazio se nao ha nested fields.
    nested_fields: list[NestedFieldSpec] = []
    #: Colunas usadas como chave de merge ao salvar em Delta.
    merge_keys: list[str]
    #: Colunas de particao, na ordem dos niveis.
    partition_columns: list[str]
    #: Coluna de timestamp usada para ordenacao na deduplicacao (mais recente primeiro).
    timestamp_field: str
    #: Enrichments a aplicar. Vazio se nao ha enriquecimentos.
    enrichments: list[Enrichment] = []
    #: Comentarios de colunas que nao sao FieldSpec (particoes, rastreabilidade).
    extra_column_comments: dict[str, str] = {}
    #: Tamanho medio estimado de uma linha (bytes), usado no file sizing da primeira carga.
    avg_row_size: int = 340

    @classmethod
    def column_comments(cls) -> dict[str, str]:
        """Mapa de comentarios por coluna (target_name -> comentario)."""
        return {**{f.target_name: f.comment for f in cls.fields}, **cls.extra_column_comments}

    @classmethod
    def source_schema(cls) -> list[str]:
        """Nomes das colunas de origem — usados para selecionar colunas ao ler a fonte."""
        return [f.source_name for f in cls.fields]

    @classmethod
    def raw_to_staging_map(cls) -> dict[str, str]:
        """Mapa de rename: source_name -> target_name."""
        return {f.source_name: f.target_name for f in cls.fields}

    @classmethod
    def full_table_name(cls) -> str:
        """Nome completo qualificado ``database.tabela``."""
        return f"{cls.database_name}.{cls.table_name}"

"""Estado compartilhado entre os agentes no grafo LangGraph."""

from __future__ import annotations

from typing import TypedDict


class FieldDef(TypedDict):
    """Definição de um campo extraído do DDL."""
    raw_field: str        # nome na origem (ex: dt_rfrn_mvmn)
    staging_field: str    # nome no staging (ex: dt_referencia_movimento)
    raw_type: str         # tipo SQL original (ex: VARCHAR(255))
    data_type: str        # tipo Spark (ex: DateType, StringType, TimestampType)
    comment: str          # documentação do campo
    is_pk: bool           # é primary key?
    is_fk: bool           # é foreign key?
    nullable: bool        # admite nulo?
    encrypt: bool         # criptografar na ingestão (AES/ECB + base64)?
    # Opcional: contract_staging_field (stagingName do data contract, prevalece na nomenclatura)


class ProfileField(TypedDict):
    """Perfil estatístico de um campo na amostra."""
    name: str
    inferred_type: str
    null_count: int
    null_pct: float
    cardinality: int
    unique_pct: float
    min_value: str | None
    max_value: str | None
    looks_like_cents: bool       # valores em centavos? (inteiros grandes sem decimal)
    looks_like_pii: bool         # parece dado sensível?
    sample_values: list[str]     # até 5 valores de exemplo


class SchemaInfo(TypedDict):
    """Schema estruturado extraído do DDL."""
    table_name: str
    source_table: str           # tabela na origem (ex: public.organizacao)
    dataset: str                # nome do dataset (ex: vendas)
    table_comment: str          # descrição da tabela (DDL ou agente de nomenclatura)
    fields: list[FieldDef]
    pk_fields: list[str]        # nomes dos campos PK
    partition_column: str       # coluna de partição informada (--partition-col), ex: DH_INCL_RGST
    merge_keys: list[str]       # chave de merge do Delta informada (--merge-keys ou arquivo de nomenclatura)
    partition_candidates: list[str]  # campos de data candidatos a partição


class ProfileInfo(TypedDict):
    """Perfil estatístico da amostra."""
    row_count: int
    fields: list[ProfileField]
    has_monetary_fields: bool
    monetary_fields: list[str]  # campos que parecem valores monetários


class CompileError(TypedDict):
    """Erro de compilação retornado pelo validator."""
    file: str
    error: str
    agent_origin: str           # "input_gen" ou "transform_gen"


class FrameworkState(TypedDict):
    """Estado compartilhado do grafo LangGraph."""
    # Entrada
    ddl: str
    contract: str                     # YAML do data contract ODCS (--contract); substitui o DDL
    contract_table: str               # tabela do contrato (--table), obrigatória se houver mais de uma
    sample_path: str
    dataset: str
    project_name: str
    tipagem_path: str                 # planilha Tipagem.xlsx (opcional)
    llm_model: str                    # ex: openai:gpt-4o-mini (vazio = heurística)
    naming_dir: str                   # onde fica o <tabela>.json de nomenclatura revisável
    dry_run: bool
    output_dir: str                   # pasta onde os projetos são gravados (default: pasta atual)
    encrypt_columns: list[str]        # colunas (raw) a criptografar na ingestão (--encrypt)
    source_db: str                    # banco de origem: postgres | oracle | mysql | sqlserver
    partition_col: str                # coluna de partição (filtro incremental, leitura paralela, partição L1)
    merge_keys: list[str]             # colunas (raw) da chave de merge do Delta (--merge-keys)
    github_org: str                   # organização GitHub do remote origin (default: datalake-org)
    language: str                     # linguagem da transformação: pyspark | scala
    codecommit_transformation: str    # repo CodeCommit do pipeline de transformação (default: <dataset>-transformation)

    # Saída do Profiler (Agente 1)
    schema: SchemaInfo | None
    profile: ProfileInfo | None

    # Saída da Nomenclatura
    naming_source: str                # llm | heuristica | arquivo (combinados com +)
    naming_warnings: list[str]

    # Saída dos geradores (Agentes 2 e 3)
    input_files: dict[str, str]       # caminho -> conteúdo
    transform_files: dict[str, str]   # caminho -> conteúdo
    input_project_dir: str
    transform_project_dir: str

    # Saída do Validator (Agente 4)
    compile_errors: list[CompileError]
    input_compiled: bool
    validation_skipped: str           # motivo de não ter validado (dry-run, sbt ausente) ou vazio
    transform_compiled: bool

    # Controle de fluxo
    iterations: int
    max_iterations: int               # teto (default: 5)
    skip_input: bool                  # pular geração do ingestion.yml (default: False)
    status: str                       # profiling | generating | validating | fixing | done | error
    error_message: str

"""Teste end-to-end: gera projetos para a tabela organizacao.

Executa:
    python -m pytest tests/test_organizacao.py -v
"""

from __future__ import annotations

from framework.parsers.ddl_parser import parse_ddl
from framework.agents.profiler import profiler_agent
from framework.agents.input_gen import input_gen_agent
from framework.agents.transform_gen import transform_gen_agent


DDL_ORGANIZACAO = """
CREATE TABLE public.organizacao (
    id                          uuid PRIMARY KEY,
    parent_id                   uuid REFERENCES organizacao(id),
    card_delivery_address_id    uuid,
    name                        VARCHAR(255) NOT NULL,
    trade_name                  VARCHAR(255) NOT NULL,
    document                    VARCHAR(20) NOT NULL,
    type                        VARCHAR(50),
    status                      VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    external_id                 VARCHAR(100) UNIQUE,
    account_external_id         VARCHAR(100),
    auth0_org_id                VARCHAR(100) NOT NULL,
    created_at                  TIMESTAMP NOT NULL,
    updated_at                  TIMESTAMP NOT NULL
);
"""


def test_parse_ddl():
    """Testa se o parser extrai o schema corretamente."""
    schema = parse_ddl(DDL_ORGANIZACAO, dataset="vendas")

    assert schema["table_name"] == "organizacao"
    assert schema["source_table"] == "public.organizacao"
    assert schema["dataset"] == "vendas"
    assert len(schema["fields"]) == 13
    assert schema["pk_fields"] == ["id"]

    # Verifica se id é StringType (uuid → StringType)
    id_field = next(f for f in schema["fields"] if f["raw_field"] == "id")
    assert id_field["data_type"] == "StringType"
    assert id_field["is_pk"] is True

    # Verifica se created_at é TimestampType
    created_field = next(f for f in schema["fields"] if f["raw_field"] == "created_at")
    assert created_field["data_type"] == "TimestampType"


def test_profiler_agent():
    """Testa o agente profiler sem amostra."""
    state = {
        "ddl": DDL_ORGANIZACAO,
        "sample_path": "",
        "dataset": "vendas",
        "project_name": "vendas",
        "schema": None,
        "profile": None,
        "input_files": {},
        "transform_files": {},
        "input_project_dir": "",
        "transform_project_dir": "",
        "compile_errors": [],
        "input_compiled": False,
        "transform_compiled": False,
        "iterations": 0,
        "max_iterations": 5,
        "skip_input": False,
        "status": "profiling",
        "error_message": "",
    }

    result = profiler_agent(state)

    assert result["schema"] is not None
    assert result["schema"]["table_name"] == "organizacao"
    assert result["status"] == "generating"


def test_input_gen_agent():
    """Testa a geração do ingestion.yml."""
    # Primeiro roda o profiler
    state = {
        "ddl": DDL_ORGANIZACAO,
        "sample_path": "",
        "dataset": "vendas",
        "project_name": "vendas",
        "schema": None,
        "profile": None,
        "input_files": {},
        "transform_files": {},
        "input_project_dir": "",
        "transform_project_dir": "",
        "compile_errors": [],
        "input_compiled": False,
        "transform_compiled": False,
        "iterations": 0,
        "max_iterations": 5,
        "skip_input": False,
        "status": "profiling",
        "error_message": "",
    }

    state = profiler_agent(state)
    state = input_gen_agent(state)

    import yaml
    assert list(state["input_files"]) == ["ingestion-config/vendas/organizacao.ingestion.yml"]
    cfg = yaml.safe_load(state["input_files"]["ingestion-config/vendas/organizacao.ingestion.yml"])
    assert cfg["source"]["table"] == "public.organizacao"
    assert cfg["load"]["incrementalColumns"] == ["created_at", "updated_at"]


def test_transform_gen_agent():
    """Testa a geração do projeto de transformação."""
    state = {
        "ddl": DDL_ORGANIZACAO,
        "sample_path": "",
        "dataset": "vendas",
        "project_name": "vendas",
        "schema": None,
        "profile": None,
        "input_files": {},
        "transform_files": {},
        "input_project_dir": "",
        "transform_project_dir": "",
        "compile_errors": [],
        "input_compiled": False,
        "transform_compiled": False,
        "iterations": 0,
        "max_iterations": 5,
        "skip_input": False,
        "status": "profiling",
        "error_message": "",
    }

    state = profiler_agent(state)
    state = transform_gen_agent(state)

    keys = str(state["transform_files"].keys())
    assert "processor/organizacao/organizacao_model.py" in keys
    assert "processor/organizacao/organizacao_processor.py" in keys

    # Verifica se o Model contém os campos do DDL (FieldSpec, padrão das skills)
    model_content = next(v for k, v in state["transform_files"].items() if k.endswith("organizacao_model.py"))
    assert "FieldSpec(" in model_content
    assert '"parent_id"' in model_content
    assert '"auth0_org_id"' in model_content

    # Verifica se o merge key usa o PK (id) — sem nomenclatura, staging = raw
    assert 'merge_keys = ["id"]' in model_content

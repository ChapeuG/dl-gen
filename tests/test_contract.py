"""Testes do data contract (ODCS) como entrada e do ingestion.yml (modo contrato).

Executa:
    python -m pytest tests/test_contract.py -v
"""

from __future__ import annotations

import pytest
import yaml

from framework.agents.input_gen import input_gen_agent
from framework.agents.naming import naming_agent
from framework.agents.profiler import profiler_agent
from framework.agents.transform_gen import transform_gen_agent
from framework.cli import _initial_state
from framework.ingestion_config import placeholders
from framework.parsers.contract_parser import load_contract, resolve_table

CONTRACT = """
apiVersion: v3.2.0
kind: DataContract
id: 11111111-2222-3333-4444-555555555555
version: 1.2.0
status: active
dataProduct: Cartoes
servers:
  - server: prd
    environment: prd
    type: oracle
    host: db.prd
    port: 1521
    serviceName: CRTPRD
    customProperties:
      - property: secretId
        value: arn:secret:prd
schema:
  - name: cliente
    physicalName: CRT.TB_CLIENTE
    description: Clientes
    customProperties:
      - property: incrementalColumns
        value: [DH_ATLZ]
      - property: rawPath
        value: s3://raw-{env}/cartoes/cliente/
      - property: cryptographySecretArn
        value: arn:crypto
      - property: rawPartitionColumn
        value: anomesdia
    properties:
      - name: cd_cliente
        physicalName: CD_CLIENTE
        logicalType: integer
        physicalType: NUMBER(18,0)
        primaryKey: true
        primaryKeyPosition: 1
        description: Código do cliente
        customProperties:
          - property: stagingName
            value: cd_cliente_contrato
        quality:
          - metric: duplicateValues
            mustBe: 0
      - name: nu_cpf
        physicalName: NU_CPF
        physicalType: VARCHAR2(11)
        customProperties:
          - property: encrypt
            value: true
      - name: vl_limite
        logicalType: number
      - name: dh_incl
        physicalName: DH_INCL
        physicalType: DATE
        required: true
        partitioned: true
      - name: dh_atlz
        physicalName: DH_ATLZ
        physicalType: DATE
        quality:
          - metric: nullValues
            mustBe: 0
            severity: warning
    quality:
      - metric: rowCount
        mustBeGreaterThan: 0
"""


@pytest.fixture
def contract_file(tmp_path):
    path = tmp_path / "cliente.odcs.yaml"
    path.write_text(CONTRACT, encoding="utf-8")
    return str(path)


def _run(state):
    state.update(profiler_agent(state))
    state.update(naming_agent(state))
    return state


def _state(contract_file, **kw):
    args = {"ddl": None, "sample_path": None, "dataset": None, "tipagem_path": None, "llm_model": "",
            "naming_dir": "", "dry_run": True, "contract_path": contract_file, **kw}
    state = _initial_state(**args)
    state["transform_files"] = {}
    return state


# ── Parser ─────────────────────────────────────────────────────────────

def test_resolve_table_extracts_flags():
    ct = resolve_table(load_contract(CONTRACT))
    assert ct.dataset == "cartoes"
    assert ct.source_db == "oracle"
    assert ct.partition_col == "DH_INCL"
    assert ct.merge_keys == ["CD_CLIENTE"]
    assert ct.encrypt_columns == ["NU_CPF"]


def test_invalid_contracts():
    with pytest.raises(ValueError, match="DataContract"):
        load_contract("kind: Outro\napiVersion: v3.2.0\nschema: []")
    with pytest.raises(ValueError, match="apiVersion"):
        load_contract("kind: DataContract\napiVersion: 1.1.0\nschema: [{name: a, properties: [{name: b}]}]")
    multi = yaml.safe_load(CONTRACT)
    multi["schema"].append({**multi["schema"][0], "name": "outra"})
    with pytest.raises(ValueError, match="--table"):
        resolve_table(load_contract(yaml.safe_dump(multi)))
    assert resolve_table(load_contract(yaml.safe_dump(multi)), "outra").table["name"] == "outra"


def test_initial_state_from_contract_and_flag_override(contract_file):
    state = _state(contract_file)
    assert (state["dataset"], state["source_db"], state["partition_col"]) == ("cartoes", "oracle", "DH_INCL")
    assert state["merge_keys"] == ["CD_CLIENTE"] and state["encrypt_columns"] == ["NU_CPF"]
    assert state["ddl"] == ""

    state = _state(contract_file, dataset="outro", partition_col="DH_ATLZ")
    assert state["dataset"] == "outro" and state["partition_col"] == "DH_ATLZ"


def test_ddl_or_contract_required():
    import click
    with pytest.raises(click.UsageError):
        _initial_state(None, None, None, None, "", "", True)


def test_schema_from_contract(contract_file):
    state = _run(_state(contract_file))
    schema = state["schema"]
    types = {f["raw_field"]: f["data_type"] for f in schema["fields"]}
    assert types == {"CD_CLIENTE": "DecimalType(18,0)", "NU_CPF": "StringType", "vl_limite": "DecimalType(38,10)",
                     "DH_INCL": "TimestampType", "DH_ATLZ": "TimestampType"}  # DATE do Oracle → timestamp
    assert schema["source_table"] == "CRT.TB_CLIENTE"
    assert schema["partition_column"] == "DH_INCL"
    assert [f["raw_field"] for f in schema["fields"] if f["encrypt"]] == ["NU_CPF"]
    # stagingName do contrato prevalece sobre a heurística
    by_raw = {f["raw_field"]: f for f in schema["fields"]}
    assert by_raw["CD_CLIENTE"]["staging_field"] == "cd_cliente_contrato"
    assert by_raw["CD_CLIENTE"]["comment"] == "Código do cliente"


# ── Input: ingestion.yml ───────────────────────────────────────────────

def test_ingestion_yml(contract_file):
    files = input_gen_agent(_run(_state(contract_file)))["input_files"]
    assert list(files) == ["ingestion-config/cartoes/cliente.ingestion.yml"]
    cfg = yaml.safe_load(files["ingestion-config/cartoes/cliente.ingestion.yml"])

    assert cfg["apiVersion"] == "ingestion/v1"
    assert cfg["contract"] == {"id": "11111111-2222-3333-4444-555555555555", "version": "1.2.0", "status": "active"}
    assert cfg["source"] == {"type": "oracle", "table": "CRT.TB_CLIENTE", "servers": {
        "prd": {"host": "db.prd", "port": 1521, "database": "CRTPRD", "secretId": "arn:secret:prd"}}}
    assert cfg["load"]["mode"] == "incremental"
    assert cfg["load"]["incrementalColumns"] == ["DH_INCL", "DH_ATLZ"]
    assert cfg["target"]["path"] == "s3://raw-{env}/cartoes/cliente/"
    assert cfg["target"]["database"] == "raw_cartoes"
    assert cfg["target"]["partitionColumn"] == "anomesdia"
    assert cfg["encryption"]["columns"] == ["NU_CPF"] and cfg["encryption"]["secretArn"] == "arn:crypto"
    assert cfg["quality"] == [
        {"check": "unique", "columns": ["CD_CLIENTE"], "severity": "error"},
        {"check": "notNull", "columns": ["DH_ATLZ"], "severity": "warning"},
        {"check": "rowCount", "mustBeGreaterThan": 0, "severity": "error"},
    ]
    assert placeholders(cfg) == []


def test_transformation_fed_by_contract(contract_file):
    files = transform_gen_agent(_run(_state(contract_file)))["transform_files"]
    assert any(k.startswith("cartoes-transformation/") for k in files)
    model = next(v for k, v in files.items() if k.endswith("Model.scala") and "Cliente" in k)
    assert "cd_cliente_contrato" in model


def test_ddl_input_mode_contrato_marks_placeholders():
    state = {"ddl": "CREATE TABLE public.t (id int PRIMARY KEY, created_at timestamp);", "dataset": "ds",
             "sample_path": "", "llm_model": "", "naming_dir": "", "dry_run": True, "transform_files": {}}
    cfg = yaml.safe_load(next(iter(input_gen_agent(_run(state))["input_files"].values())))
    assert cfg["contract"]["id"] == "sem-contrato"
    assert "source.servers.prd.secretId" in placeholders(cfg)
    assert "target.partitionColumn" in placeholders(cfg)  # sem default: vem do contrato
    assert cfg["load"]["incrementalColumns"] == ["created_at"]

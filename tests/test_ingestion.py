"""Testes da tipagem oficial, do ingestion.yml (criptografia, origem, partição) e da transformação.

Executa:
    python -m pytest tests/test_ingestion.py -v
"""

from __future__ import annotations

import json

import pytest
import yaml

from framework.agents.input_gen import input_gen_agent
from framework.agents.naming import naming_agent
from framework.agents.profiler import profiler_agent
from framework.agents.transform_gen import transform_gen_agent
from framework.parsers.ddl_parser import parse_ddl
from framework.standards.tipagem import is_valid_spark_type, load_type_map

DDL_CLIENTE = """
CREATE TABLE public.cliente (
    id          uuid PRIMARY KEY,
    nu_cpf      INT NOT NULL,
    email       VARCHAR(255),
    ativo       bool,
    limite      numeric(12,2),
    nascimento  date,
    tags        text[],
    created_at  datetime NOT NULL,
    updated_at  timestamp NOT NULL
);
"""


def _state(ddl=DDL_CLIENTE, **extra):
    return {"ddl": ddl, "dataset": "vendas", "sample_path": "", "llm_model": "",
            "naming_dir": "", "dry_run": True, "transform_files": {}, **extra}


def _run(ddl=DDL_CLIENTE, **extra):
    state = _state(ddl, **extra)
    state.update(profiler_agent(state))
    state.update(naming_agent(state))
    return state


def _file(files: dict, suffix: str) -> str:
    return next(v for k, v in files.items() if k.endswith(suffix))


def _yml(state) -> dict:
    files = input_gen_agent(state)["input_files"]
    return yaml.safe_load(next(iter(files.values())))


# ── Tipagem ────────────────────────────────────────────────────────────

def test_official_type_table():
    types = {f["raw_field"]: f["data_type"] for f in parse_ddl(DDL_CLIENTE)["fields"]}
    assert types == {
        "id": "StringType",
        "nu_cpf": "IntegerType",
        "email": "StringType",
        "ativo": "BooleanType",
        "limite": "DecimalType(12,2)",
        "nascimento": "DateType",
        "tags": "ArrayType(StringType)",
        "created_at": "TimestampType",
        "updated_at": "TimestampType",
    }
    assert all(is_valid_spark_type(t) for t in types.values())


def test_tipagem_xlsx_with_official_headers_and_invalid_type(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Tipo Origem", "Tipo Final"])
    ws.append(["bigint", "LongType"])
    ws.append(["smallint", "ShortType"])
    ok = tmp_path / "ok.xlsx"
    wb.save(ok)
    assert load_type_map(ok) == {"bigint": "LongType", "smallint": "ShortType"}

    ws.append(["int", "IntegerTyp"])  # erro de digitação
    bad = tmp_path / "bad.xlsx"
    wb.save(bad)
    with pytest.raises(ValueError, match="IntegerTyp"):
        load_type_map(bad)


# ── Ingestão (ingestion.yml) ───────────────────────────────────────────

def test_ingestion_yml_from_ddl():
    files = input_gen_agent(_run())["input_files"]
    assert list(files) == ["ingestion-config/vendas/cliente.ingestion.yml"]
    cfg = yaml.safe_load(files["ingestion-config/vendas/cliente.ingestion.yml"])
    assert cfg["source"]["type"] == "postgres" and cfg["source"]["table"] == "public.cliente"
    assert cfg["load"] == {"mode": "incremental", "incrementalColumns": ["created_at", "updated_at"], "fetchSize": 150000,
                           "parallel": {"days": 1, "queries": 1, "column": "created_at"}}
    assert [c["name"] for c in cfg["columns"]][:3] == ["id", "nu_cpf", "email"]
    assert "encryption" not in cfg


def test_ingestion_encrypts_configured_columns():
    cfg = _yml(_run(encrypt_columns=["NU_CPF", "email"]))
    assert cfg["encryption"]["columns"] == ["nu_cpf", "email"]
    assert cfg["encryption"]["algorithm"] == "AES/ECB" and cfg["encryption"]["secretField"] == "AES_KEY"
    assert {c["name"] for c in cfg["columns"] if c.get("encrypt")} == {"nu_cpf", "email"}


def test_encrypted_column_is_string_in_transformation():
    state = _run(encrypt_columns=["nu_cpf"])
    model = _file(transform_gen_agent(state)["transform_files"], "ClienteModel.scala")
    line = next(line for line in model.splitlines() if 'FieldSpec("nu_cpf"' in line)
    # Já chega criptografado (base64): StringType, sem transformação
    assert ", StringType, " in line
    assert "encrypted = true" in line
    assert "transformation = None" in line


def test_encrypt_unknown_column_fails():
    with pytest.raises(ValueError, match="nao_existe"):
        _run(encrypt_columns=["nao_existe"])


def test_encrypt_flag_persists_in_naming_file(tmp_path):
    _run(encrypt_columns=["nu_cpf"], naming_dir=str(tmp_path), dry_run=False)
    saved = json.loads((tmp_path / "cliente.json").read_text(encoding="utf-8"))
    assert {f["raw_field"]: f["encrypt"] for f in saved["fields"]}["nu_cpf"] is True

    # Próxima execução sem --encrypt: o arquivo revisado mantém a criptografia
    assert _yml(_run(naming_dir=str(tmp_path)))["encryption"]["columns"] == ["nu_cpf"]


def test_table_without_date_column_is_full_load():
    ddl = "CREATE TABLE public.cred_final (cd_credenciadora INTEGER NOT NULL, data DATE NOT NULL);"
    load = _yml(_run(ddl))["load"]
    assert load["mode"] == "full" and load["incrementalColumns"] == []


# ── Banco de origem ────────────────────────────────────────────────────

def test_oracle_source():
    ddl = "CREATE TABLE CLC.LANCAMENTO (CD_LNCM NUMBER(18,0), DT_RFRN DATE, created_at TIMESTAMP);"
    state = _run(ddl, source_db="oracle", merge_keys=["CD_LNCM"])
    types = {f["raw_field"]: f["data_type"] for f in state["schema"]["fields"]}
    assert types == {"CD_LNCM": "DecimalType(18,0)", "DT_RFRN": "TimestampType", "created_at": "TimestampType"}
    assert _yml(state)["source"]["type"] == "oracle"

    # A ingestão grava as colunas em minúsculo; a transformação lê em minúsculo
    model_t = _file(transform_gen_agent(state)["transform_files"], "LancamentoModel.scala")
    assert 'FieldSpec("cd_lncm", ' in model_t


def test_unknown_source_fails():
    with pytest.raises(ValueError, match="db2"):
        _run(source_db="db2")


# ── Coluna de partição (--partition-col) ───────────────────────────────

DDL_LANCAMENTO = """
CREATE TABLE CLC.TBCLCR_LNCM_RECB (
    CD_LNCM       NUMBER(18,0) NOT NULL,
    DT_RFRN_MVMN  DATE,
    DH_INCL_RGST  TIMESTAMP NOT NULL,
    VL_LNCM       NUMBER(15,2)
);
"""


def test_partition_col_drives_ingestion_and_transformation():
    state = _run(DDL_LANCAMENTO, dataset="financeiro", source_db="oracle", partition_col="dh_incl_rgst",
                 merge_keys=["CD_LNCM"])
    assert state["schema"]["partition_column"] == "DH_INCL_RGST"

    load = _yml(state)["load"]
    assert load["incrementalColumns"] == ["DH_INCL_RGST"]  # só a coluna informada no filtro
    assert load["parallel"]["column"] == "DH_INCL_RGST"

    transform = transform_gen_agent(state)["transform_files"]
    proc_t = _file(transform, "TbclcrLncmRecbProcessor.scala")
    staging = next(f["staging_field"] for f in state["schema"]["fields"] if f["raw_field"] == "DH_INCL_RGST")
    partition = f"dt_{staging.split('_', 1)[1]}_particao"
    assert f'.withColumn("{partition}", date_format(col("{staging}"), "yyyyMMdd"))' in proc_t


def test_partition_col_overrides_created_at():
    assert _yml(_run(partition_col="nascimento"))["load"]["incrementalColumns"] == ["nascimento"]


def test_partition_col_validation():
    with pytest.raises(ValueError, match="não existe"):
        _run(partition_col="DH_INEXISTENTE")
    with pytest.raises(ValueError, match="precisa ser data/timestamp"):
        _run(partition_col="email")


# ── Chave de merge (--merge-keys) ──────────────────────────────────────

DDL_CRED = """
CREATE TABLE public.cred_final (
    cd_credenciadora INTEGER NOT NULL,
    nm_produto       VARCHAR(100) NOT NULL,
    data             DATE NOT NULL,
    predito_final    DOUBLE PRECISION
);
"""


def _merge_conditions(state) -> list[str]:
    import re
    model = _file(transform_gen_agent(state)["transform_files"], "CredFinalModel.scala")
    line = next(line for line in model.splitlines() if "override val mergeKeys" in line)
    return re.findall(r'"([^"]+)"', line)


def test_merge_keys_override_heuristic():
    state = _run(DDL_CRED, merge_keys=["CD_CREDENCIADORA", "nm_produto", "data"])
    assert state["schema"]["merge_keys"] == ["cd_credenciadora", "nm_produto", "data"]

    by_raw = {f["raw_field"]: f["staging_field"] for f in state["schema"]["fields"]}
    expected = [by_raw[k] for k in ("cd_credenciadora", "nm_produto", "data")]
    assert _merge_conditions(state) == expected


def test_merge_keys_without_option_uses_single_column_fallback(capsys):
    assert len(_merge_conditions(_run(DDL_CRED))) == 1
    assert "informe --merge-keys" in capsys.readouterr().out


def test_merge_keys_validation():
    with pytest.raises(ValueError, match="nao_existe"):
        _run(DDL_CRED, merge_keys=["cd_credenciadora", "nao_existe"])


def test_merge_keys_persist_in_naming_file(tmp_path):
    _run(DDL_CRED, merge_keys=["cd_credenciadora", "data"], naming_dir=str(tmp_path), dry_run=False)
    saved = json.loads((tmp_path / "cred_final.json").read_text(encoding="utf-8"))
    assert saved["merge_keys"] == ["cd_credenciadora", "data"]

    # Próxima execução sem --merge-keys: vale o arquivo
    assert len(_merge_conditions(_run(DDL_CRED, naming_dir=str(tmp_path)))) == 2


# ── Arquivos de repositório e gravação ─────────────────────────────────

def test_repo_files_of_transformation():
    transform = transform_gen_agent(_run(codecommit_transformation="vendas-transf", github_org="acme"))["transform_files"]
    pipeline = _file(transform, ".github/workflows/pipeline.yml")
    assert pipeline.count("git push --mirror codecommit::us-east-2://vendas-transf") == 3
    assert "github.com/project-slug: acme/vendas-transformation" in _file(transform, "catalog-info.yaml")
    assert "target/" in _file(transform, ".gitignore")


def test_validator_writes_yml_and_project_with_git(tmp_path, monkeypatch):
    import subprocess
    from framework.agents import validator

    monkeypatch.setattr(validator.shutil, "which", lambda name: None)  # sem sbt
    state = _run()
    state.update(input_gen_agent(state))
    state.update(transform_gen_agent(state))
    state.update({"output_dir": str(tmp_path), "dry_run": False})
    result = validator.validator_agent(state)

    assert result["validation_skipped"] == "sbt não encontrado no PATH"
    assert (tmp_path / "ingestion-config" / "vendas" / "cliente.ingestion.yml").exists()
    assert not (tmp_path / "ingestion-config" / ".git").exists()  # o yml não vira repositório
    project = tmp_path / "vendas-transformation"
    assert (project / "project" / "plugins.sbt").exists()
    remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=project, capture_output=True, text=True)
    assert remote.stdout.strip() == "https://github.com/datalake-org/vendas-transformation.git"
    branch = subprocess.run(["git", "symbolic-ref", "--short", "HEAD"], cwd=project, capture_output=True, text=True)
    assert branch.stdout.strip() == "main"


def test_dry_run_writes_nothing(tmp_path):
    from framework.agents import validator

    state = _run()
    state.update(input_gen_agent(state))
    state.update({"output_dir": str(tmp_path), "dry_run": True})
    assert validator.validator_agent(state)["validation_skipped"] == "dry-run"
    assert list(tmp_path.iterdir()) == []


# ── Transformação no padrão das skills ────────────────────────

def test_transformation_follows_skills_structure():
    state = _run(merge_keys=["id"])
    files = transform_gen_agent(state)["transform_files"]
    base = "vendas-transformation/src/main/scala/br/com/datalake/"
    for rel in ("Main.scala", "error/SparkErrorHandler.scala", "processor/cliente/ClienteModel.scala",
                "processor/cliente/ClienteProcessor.scala", "utils/TableModel.scala", "utils/FieldSpec.scala",
                "utils/TransformColumn.scala", "utils/DeltaWritePattern.scala", "utils/HiveTableManager.scala",
                "utils/DataFrameUtils.scala", "utils/FileUtils.scala", "utils/Enrichment.scala"):
        assert base + rel in files, rel
    assert "vendas-transformation/docs_sdd/cliente_sdd_doc.md" in files

    main = files[base + "Main.scala"]
    assert "case ClienteModel.tableName => ClienteProcessor.process(params)" in main

    processor = files[base + "processor/cliente/ClienteProcessor.scala"]
    order = ["DataFrameUtils.renameColumns", "TransformColumn(f)", "ApplyEnrichment.applyAll",
             "DeltaWritePattern.dedup", "addTraceabilityFields", "persist(StorageLevel.MEMORY_AND_DISK)",
             "DeltaWritePattern.save", "HiveTableManager.createTable", "registerPartitions", "unpersist()"]
    positions = [processor.index(step) for step in order]
    assert positions == sorted(positions)
    assert '.withColumn("dt_atualizacao_registro_particao", lit(runDateYyyymmdd))' in processor

    model = files[base + "processor/cliente/ClienteModel.scala"]
    by_raw = {f["raw_field"]: f for f in state["schema"]["fields"]}
    created = by_raw["created_at"]["staging_field"]
    # Timestamp: normalizeTimestamp + to_timestamp (default); boolean e decimal com cast
    assert f'FieldSpec("created_at", "{created}", TimestampType' in model
    assert 'DecimalType(12,2)' in model
    assert 'FieldSpec("@timestamp", "dh_criacao_data_lake", TimestampType' in model

    sdd = files["vendas-transformation/docs_sdd/cliente_sdd_doc.md"]
    for section in ("## 1. Identificação", "## 5. Campos Aninhados", "## 10. Escrita e Persistência"):
        assert section in sdd


def test_transformation_requires_merge_key():
    ddl = "CREATE TABLE public.log (mensagem VARCHAR(100), dh_evento TIMESTAMP);"
    with pytest.raises(ValueError, match="--merge-keys"):
        transform_gen_agent(_run(ddl))


def test_naming_file_overrides_transformation(tmp_path):
    _run(DDL_CRED, merge_keys=["cd_credenciadora"], naming_dir=str(tmp_path), dry_run=False)
    path = tmp_path / "cred_final.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    by_raw = {f["raw_field"]: f for f in data["fields"]}
    assert by_raw["nm_produto"]["transformation"] == "default"

    by_raw["nm_produto"]["transformation"] = None
    by_raw["data"]["transformation"] = "format"
    by_raw["data"]["source_format"] = "yyyyMMdd"
    path.write_text(json.dumps(data), encoding="utf-8")

    model = _file(transform_gen_agent(_run(DDL_CRED, naming_dir=str(tmp_path)))["transform_files"], "CredFinalModel.scala")
    produto = next(line for line in model.splitlines() if 'FieldSpec("nm_produto"' in line)
    data_line = next(line for line in model.splitlines() if 'FieldSpec("data"' in line)
    assert "transformation = None" in produto
    assert 'sourceFormat = Some("yyyyMMdd"), transformation = Some("format")' in data_line

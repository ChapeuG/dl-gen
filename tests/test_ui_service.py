"""Lógica da interface (framework.ui.service): formulário → contrato → nomenclatura → validação → geração."""

from __future__ import annotations

from pathlib import Path

import yaml

from framework.parsers.contract_parser import custom_props, load_contract, resolve_table
from framework.ui import service

DDL = """
CREATE TABLE public.cliente (
    id          INTEGER PRIMARY KEY,
    nu_cpf      VARCHAR(11),
    nome        VARCHAR(100) NOT NULL,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP
);
"""


def _filled():
    form, rows = service.columns_from_ddl(DDL)
    f = {**service.empty_form(), **form, "dataset": "vendas",
         "rawPartitionColumn": "dt_ingestao", "incrementalColumns": ["updated_at"],
         "cryptographySecretArn": "arn:crypto"}
    for r in rows:
        r["encrypt"] = r["name"] == "nu_cpf"
    servers = [{"environment": "prd", "host": "db", "port": 5432.0, "database": "crm", "secretId": "arn:secret"}]
    return f, servers, rows


def test_columns_from_ddl():
    form, rows = service.columns_from_ddl(DDL)
    assert form == {"table": "cliente", "physicalName": "public.cliente", "description": ""}
    by = {r["name"]: r for r in rows}
    assert by["id"]["primaryKey"] and by["id"]["logicalType"] == "integer"
    assert by["created_at"]["partitioned"]  # candidato a coluna incremental
    assert by["nome"]["required"] and not by["nu_cpf"]["required"]


def test_build_contract_is_valid_odcs_and_resolves():
    form, servers, rows = _filled()
    contract = service.build_contract(form, servers, rows)
    ct = resolve_table(load_contract(service.dump_contract(contract)))
    assert (ct.dataset, ct.source_db, ct.partition_col) == ("vendas", "postgres", "created_at")
    assert ct.merge_keys == ["id"] and ct.encrypt_columns == ["nu_cpf"]
    assert contract["servers"][0]["port"] == 5432 and custom_props(contract["servers"][0])["secretId"] == "arn:secret"
    tp = custom_props(contract["schema"][0])
    assert tp["incrementalColumns"] == ["updated_at"] and tp["rawPartitionColumn"] == "dt_ingestao"
    assert [q["metric"] for q in contract["schema"][0]["quality"]] == ["duplicateValues", "rowCount"]


def test_odcs_schema_if_available():
    """Confere com o JSON Schema oficial quando ele estiver em cache local (sem rede no teste)."""
    import json
    import os

    path = os.environ.get("ODCS_SCHEMA")
    if not path or not Path(path).exists():
        return
    import jsonschema
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    form, servers, rows = _filled()
    errors = list(jsonschema.validators.validator_for(schema)(schema).iter_errors(service.build_contract(form, servers, rows)))
    assert errors == []


def test_naming_proposal_and_edit_roundtrip():
    form, servers, rows = _filled()
    text = service.dump_contract(service.build_contract(form, servers, rows))
    result = service.propose_naming(text)
    assert result.source == "heuristica"
    by = {r["raw_field"]: r for r in result.rows}
    assert by["nu_cpf"]["encrypt"] and by["id"]["primaryKey"]

    by["nome"]["staging_field"] = "nm_cliente"
    by["nome"]["comment"] = "Nome do cliente"
    contract = service.build_contract(form, servers, rows, service.naming_map(result.rows))
    prop = next(p for p in contract["schema"][0]["properties"] if p["name"] == "nome")
    assert custom_props(prop)["stagingName"] == "nm_cliente" and prop["description"] == "Nome do cliente"
    # a próxima proposta respeita o que foi editado
    again = {r["raw_field"]: r for r in service.propose_naming(service.dump_contract(contract)).rows}
    assert again["nome"]["staging_field"] == "nm_cliente"


def test_form_from_contract_roundtrip():
    form, servers, rows = _filled()
    text = service.dump_contract(service.build_contract(form, servers, rows))
    form2, servers2, rows2 = service.form_from_contract(text)
    assert form2["dataset"] == "vendas" and form2["rawPartitionColumn"] == "dt_ingestao"
    assert servers2[0]["secretId"] == "arn:secret"
    assert [r["name"] for r in rows2] == [r["name"] for r in rows]
    assert next(r for r in rows2 if r["name"] == "nu_cpf")["encrypt"] is True


def test_validation_ok_and_previews():
    form, servers, rows = _filled()
    v = service.validate(service.build_contract(form, servers, rows))
    assert v.ok, [c for c in v.checks if c.level == "error"]
    assert "ingestion-config/vendas/cliente.ingestion.yml" in v.files
    assert any(k.startswith("vendas-transformation/") for k in v.files)


def test_validation_reports_missing_fields():
    form, servers, rows = _filled()
    form["rawPartitionColumn"] = ""
    servers[0]["secretId"] = ""
    for r in rows:
        r["primaryKey"] = False
    v = service.validate(service.build_contract(form, servers, rows))
    errors = {c.title for c in v.checks if c.level == "error"}
    assert {"Chave primária marcada", "Secret do ambiente prd", "Coluna de partição da raw"} <= errors
    assert not v.ok and v.files == {}


def test_validation_reports_naming_violation():
    form, servers, rows = _filled()
    contract = service.build_contract(form, servers, rows, {"nome": {"staging_field": "Nome Do Cliente", "comment": "x"}})
    v = service.validate(contract)
    naming = next(c for c in v.checks if c.title == "Padrão de nomenclatura")
    assert naming.level == "error" and "nome" in naming.detail


def test_generate_writes_everything(tmp_path):
    form, servers, rows = _filled()
    r = service.generate(service.build_contract(form, servers, rows), str(tmp_path))
    assert r.contract_path == tmp_path / "contracts" / "vendas" / "cliente.odcs.yaml"
    assert (tmp_path / "ingestion-config" / "vendas" / "cliente.ingestion.yml").exists()
    assert (tmp_path / "vendas-transformation" / "pyproject.toml").exists()
    assert (tmp_path / "naming" / "cliente.json").exists()
    cfg = yaml.safe_load((tmp_path / "ingestion-config" / "vendas" / "cliente.ingestion.yml").read_text(encoding="utf-8"))
    assert cfg["encryption"]["columns"] == ["nu_cpf"]


def test_generate_without_folder_uses_default(tmp_path, monkeypatch):
    monkeypatch.setenv(service.OUTPUT_DIR_ENV, str(tmp_path / "padrao"))
    form, servers, rows = _filled()
    r = service.generate(service.build_contract(form, servers, rows), "  ")
    assert r.output_dir == tmp_path / "padrao"
    assert (tmp_path / "padrao" / "contracts" / "vendas" / "cliente.odcs.yaml").exists()


def test_language_round_trips_through_contract(tmp_path):
    form, servers, rows = _filled()
    contract = service.build_contract({**form, "transformationLanguage": "scala"}, servers, rows)
    text = service.dump_contract(contract)
    assert "transformationLanguage" in text
    assert service.form_from_contract(text)[0]["transformationLanguage"] == "scala"
    r = service.generate(contract, str(tmp_path))
    assert (tmp_path / "vendas-transformation" / "build.sbt").exists()
    assert not (tmp_path / "vendas-transformation" / "main.py").exists()
    assert r.files

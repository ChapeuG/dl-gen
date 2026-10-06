"""Interface (Streamlit) de ponta a ponta com o AppTest: contrato → campos → validação → geração."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "framework" / "ui" / "app.py")

DDL = """CREATE TABLE public.cliente (
  id INTEGER PRIMARY KEY,
  nu_cpf VARCHAR(11),
  nome VARCHAR(100) NOT NULL,
  created_at TIMESTAMP NOT NULL
);"""


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label.startswith(label))


def _text(at: AppTest, label: str):
    return next(t for t in at.text_input if t.label.startswith(label))


def test_full_flow(tmp_path, monkeypatch):
    from framework.agents import validator
    monkeypatch.setattr(validator.shutil, "which", lambda name: None)  # sem sbt

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert "Data Contract Studio" in at.title[0].value

    # Etapa 1 — importa a DDL e preenche o obrigatório
    at.text_area[0].set_value(DDL).run()
    _button(at, "Importar colunas da DDL").click().run()
    assert [c["name"] for c in at.session_state.columns] == ["id", "nu_cpf", "nome", "created_at"]
    assert _button(at, "Próximo: campos").disabled  # falta o dataset

    _text(at, "Dataset").set_value("vendas").run()
    _text(at, "Coluna de partição da raw").set_value("dt_ingestao").run()
    # a tabela de servidores é um data_editor: preenche pelo estado
    at.session_state.servers = [{"environment": "prd", "host": "db", "port": 5432, "database": "crm", "secretId": "arn:secret"}]
    _button(at, "Próximo: campos").click().run()
    assert at.session_state.step == 1

    # Etapa 2 — nomenclatura proposta e editada
    rows = {r["raw_field"]: r for r in at.session_state.naming_rows}
    assert rows["nome"]["staging_field"].startswith("nm_")
    rows["nome"]["staging_field"] = "nm_cliente"
    at.session_state.naming_rows = list(rows.values())
    _button(at, "Próximo: validar").click().run()
    assert at.session_state.step == 2

    # Etapa 3 — validação ok
    assert at.session_state.validation.ok, [c for c in at.session_state.validation.checks if c.level == "error"]
    assert any("Tudo certo" in s.value for s in at.success) or any("Tudo certo" in w.value for w in at.warning)
    _button(at, "Próximo: gerar").click().run()
    assert at.session_state.step == 3

    # Etapa 4 — geração
    _text(at, "Pasta de saída").set_value(str(tmp_path)).run()
    _button(at, "Gerar arquivos").click().run()
    assert not at.exception
    assert any("Pronto!" in s.value for s in at.success)
    contract = (tmp_path / "contracts" / "vendas" / "cliente.odcs.yaml").read_text(encoding="utf-8")
    assert "nm_cliente" in contract  # a edição da etapa 2 foi para o contrato
    assert (tmp_path / "ingestion-config" / "vendas" / "cliente.ingestion.yml").exists()
    assert (tmp_path / "vendas-transformation" / "build.sbt").exists()


def test_validation_blocks_generation_without_secret():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_area[0].set_value(DDL).run()
    _button(at, "Importar colunas da DDL").click().run()
    _text(at, "Dataset").set_value("vendas").run()
    _text(at, "Coluna de partição da raw").set_value("dt_ingestao").run()
    _button(at, "Próximo: campos").click().run()
    _button(at, "Próximo: validar").click().run()

    assert not at.session_state.validation.ok
    assert any("impedem a geração" in e.value for e in at.error)
    assert _button(at, "Próximo: gerar").disabled

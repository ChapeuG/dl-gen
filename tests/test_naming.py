"""Testes da padrão de nomenclatura: parser, tipagem, heurística, validação e subgrafo LangGraph.

Executa:
    python -m pytest tests/test_naming.py -v
"""

from __future__ import annotations

import json

from langchain_core.runnables import RunnableLambda

from framework.agents import naming
from framework.agents.naming import NamingProposal, naming_agent
from framework.agents.transform_gen import render_field_block, transform_gen_agent
from framework.parsers.ddl_parser import parse_ddl
from framework.standards.glossary import propose_field
from framework.standards.nomenclatura import load_padroes_text, validate_naming
from framework.standards.tipagem import load_type_map

DDL_ORGANIZACAO = """
CREATE TABLE public.organizacao (
    id                          uuid PRIMARY KEY,
    parent_id                   uuid REFERENCES organizacao(id),
    name                        VARCHAR(255) NOT NULL,
    trade_name                  VARCHAR(255) NOT NULL,
    document                    VARCHAR(20) NOT NULL,
    type                        VARCHAR(50),
    status                      VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    created_at                  TIMESTAMP NOT NULL,
    updated_at                  TIMESTAMP NOT NULL
);
"""


def _state(schema, **extra):
    return {"schema": schema, "profile": None, "llm_model": "", "naming_dir": "", "dry_run": True,
            "transform_files": {}, **extra}


# ── Parser ─────────────────────────────────────────────────────────────

def test_parser_keeps_decimal_precision_and_comments():
    ddl = """
    CREATE TABLE vendas (
        vl_total DECIMAL(10,2) NOT NULL COMMENT 'Valor total, com impostos',
        -- comentário de linha, com vírgula
        amount NUMERIC(18, 4),
        rate double precision,
        PRIMARY KEY (vl_total, amount)
    ) COMMENT 'Vendas consolidadas';
    """
    schema = parse_ddl(ddl)
    by_raw = {f["raw_field"]: f for f in schema["fields"]}

    assert list(by_raw) == ["vl_total", "amount", "rate"]
    assert by_raw["vl_total"]["data_type"] == "DecimalType(10,2)"
    assert by_raw["vl_total"]["comment"] == "Valor total, com impostos"
    assert by_raw["amount"]["data_type"] == "DecimalType(18,4)"
    assert by_raw["rate"]["data_type"] == "DoubleType"
    assert schema["pk_fields"] == ["vl_total", "amount"]
    assert schema["table_comment"] == "Vendas consolidadas"


def test_tipagem_xlsx_overrides_default_map(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Tipo SQL", "Descrição", "Tipo Scala"])
    ws.append(["VARCHAR", "texto", "StringType"])
    ws.append(["int", "inteiro", "LongType"])
    ws.append(["numeric", "decimal", "DecimalType"])
    path = tmp_path / "Tipagem.xlsx"
    wb.save(path)

    type_map = load_type_map(path)
    assert type_map == {"varchar": "StringType", "int": "LongType", "numeric": "DecimalType"}

    schema = parse_ddl("CREATE TABLE t (a INT, b NUMERIC(12,3), c NUMERIC);", type_map=type_map)
    types = [f["data_type"] for f in schema["fields"]]
    assert types == ["LongType", "DecimalType(12,3)", "DecimalType(19,2)"]


# ── Heurística e validação ─────────────────────────────────────────────

def test_heuristic_follows_naming_standard():
    schema = parse_ddl(DDL_ORGANIZACAO)
    by_raw = {f["raw_field"]: f for f in schema["fields"]}

    def staging(raw):
        return propose_field(by_raw[raw], "organizacao")[0]

    assert staging("name") == "nm_nome"
    assert staging("trade_name") == "nm_fantasia"
    assert staging("created_at") == "dh_criacao"
    assert staging("updated_at") == "dh_atualizacao"
    assert staging("id") == "id_organizacao"
    assert staging("parent_id") == "id_pai"
    assert staging("type") == "cd_tipo"
    assert staging("document") == "nu_documento"

    names = {raw: {"staging_field": staging(raw), "comment": "x"} for raw in by_raw}
    errors, _ = validate_naming(schema["fields"], names)
    assert errors == []


def test_validation_rejects_invalid_names():
    schema = parse_ddl("CREATE TABLE t (a VARCHAR(10), b VARCHAR(10), c TIMESTAMP, d INT);")
    names = {
        "a": {"staging_field": "xx_nome", "comment": "x"},                # natureza inexistente
        "b": {"staging_field": "Nm_Nome", "comment": "x"},                # maiúsculas
        "c": {"staging_field": "dh_criacao_registro", "comment": "x"},    # reservado
        # d sem nome
    }
    errors, _ = validate_naming(schema["fields"], names)
    assert {e["raw_field"] for e in errors} == {"a", "b", "c", "d"}


def test_padroes_text_is_loaded():
    text = load_padroes_text()
    assert "Quadro de Naturezas" in text
    assert "Aprovações\nTestemunhas" not in text


# ── Subgrafo LangGraph com LLM falso ───────────────────────────────────

class FakeChatModel:
    """Devolve respostas pré-definidas e registra os prompts recebidos."""

    def __init__(self, responses: list[NamingProposal]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def with_structured_output(self, schema):
        def respond(prompt_value):
            self.prompts.append(prompt_value.to_string())
            return self.responses.pop(0)
        return RunnableLambda(respond)


def _proposal(mapping: dict[str, str]) -> NamingProposal:
    return NamingProposal(
        table_comment="Cadastro de organizações.",
        fields=[{"raw_field": r, "staging_field": s, "comment": f"Descrição de {s}."} for r, s in mapping.items()],
    )


GOOD = {
    "id": "id_organizacao", "parent_id": "id_organizacao_pai", "name": "nm_organizacao",
    "trade_name": "nm_fantasia", "document": "nu_documento", "type": "cd_tipo_organizacao",
    "status": "cd_status", "created_at": "dh_criacao", "updated_at": "dh_atualizacao",
}


def test_llm_retries_with_validation_feedback(monkeypatch):
    first = {**GOOD, "name": "nome_organizacao", "created_at": "dh_criacao_registro"}
    fake = FakeChatModel([_proposal(first), _proposal({"name": "nm_organizacao", "created_at": "dh_criacao"})])
    monkeypatch.setattr(naming, "_chat_model_factory", lambda model: fake)

    schema = parse_ddl(DDL_ORGANIZACAO)
    result = naming_agent(_state(schema, llm_model="fake:model"))

    staging = {f["raw_field"]: f["staging_field"] for f in result["schema"]["fields"]}
    assert staging == GOOD
    assert result["naming_source"] == "llm"
    assert result["schema"]["table_comment"] == "Cadastro de organizações."

    # 2ª chamada só reenvia os campos inválidos, com o erro da validação
    assert len(fake.prompts) == 2
    assert "Quadro de Naturezas" in fake.prompts[0]
    retry = fake.prompts[1]
    assert "rejeitada pela validação" in retry
    assert "- name |" in retry and "- created_at |" in retry
    assert "- trade_name |" not in retry


def test_llm_unavailable_falls_back_to_heuristic(monkeypatch):
    def broken(model):
        raise ImportError("langchain-openai não instalado")
    monkeypatch.setattr(naming, "_chat_model_factory", broken)

    result = naming_agent(_state(parse_ddl(DDL_ORGANIZACAO), llm_model="openai:gpt-x"))

    assert result["naming_source"] == "heuristica"
    assert any("LLM indisponível" in w for w in result["naming_warnings"])
    errors, _ = validate_naming(result["schema"]["fields"], {
        f["raw_field"]: {"staging_field": f["staging_field"], "comment": f["comment"]}
        for f in result["schema"]["fields"]
    })
    assert errors == []


def test_naming_file_is_source_of_truth(tmp_path, monkeypatch):
    schema = parse_ddl(DDL_ORGANIZACAO)
    (tmp_path / "organizacao.json").write_text(json.dumps({
        "table_comment": "Organizações revisadas.",
        "fields": [{"raw_field": r, "staging_field": s, "comment": "Revisado."} for r, s in GOOD.items() if r != "status"],
    }), encoding="utf-8")

    fake = FakeChatModel([_proposal({"status": "cd_situacao"})])
    monkeypatch.setattr(naming, "_chat_model_factory", lambda model: fake)

    result = naming_agent(_state(schema, llm_model="fake:model", naming_dir=str(tmp_path), dry_run=False))

    staging = {f["raw_field"]: f["staging_field"] for f in result["schema"]["fields"]}
    assert staging == {**GOOD, "status": "cd_situacao"}
    assert result["naming_source"] == "arquivo+llm"
    assert "- status |" in fake.prompts[0] and "- name |" not in fake.prompts[0]

    saved = json.loads((tmp_path / "organizacao.json").read_text(encoding="utf-8"))
    assert saved["table_comment"] == "Organizações revisadas."
    assert {f["raw_field"]: f["staging_field"] for f in saved["fields"]}["status"] == "cd_situacao"


# ── Geração Scala ──────────────────────────────────────────────────────

def test_model_field_uses_staging_camel_case(monkeypatch):
    monkeypatch.setattr(naming, "_chat_model_factory", lambda model: FakeChatModel([_proposal(GOOD)]))
    state = _state(parse_ddl(DDL_ORGANIZACAO), llm_model="fake:model")
    state.update(naming_agent(state))

    block = render_field_block(state["schema"])
    assert ('final val nmFantasia = ModelField(rawField = "trade_name", stagingField = "nm_fantasia", '
            'dataType = StringType, comment = "Descrição de nm_fantasia.")') in block

    files = transform_gen_agent({**state, "schema": state["schema"]})["transform_files"]
    model = next(v for k, v in files.items() if k.endswith("OrganizacaoModel.scala"))
    processor = next(v for k, v in files.items() if k.endswith("OrganizacaoProcessor.scala"))
    assert ('FieldSpec("trade_name", "nm_fantasia", StringType, "Descrição de nm_fantasia.", '
            'transformation = Some("default"))') in model
    # Identificador preserva o case (sem TRIM+UPPER)
    assert 'FieldSpec("id", "id_organizacao", StringType, "Descrição de id_organizacao.", transformation = None)' in model
    assert 'override val mergeKeys: Seq[String] = Seq("id_organizacao")' in model
    assert 'override val tableComment: String = "Cadastro de organizações."' in model
    assert 'Seq("dt_criacao_particao", "dt_atualizacao_registro_particao")' in model
    assert '.withColumn("dt_criacao_particao", date_format(col("dh_criacao"), "yyyyMMdd"))' in processor

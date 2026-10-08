"""Agente de Nomenclatura — aplica o padrão de nomenclatura aos campos do DDL.

Para cada campo gera stagingField (natureza_termo_qualificadores, em português),
e comment, usados no FieldSpec do model PySpark.
O dataType vem da planilha Tipagem.xlsx / mapeamento do parser — não do LLM.

Subgrafo LangGraph:

    carregar_arquivo ──(tudo definido)──────────────┐
          │                                          ▼
          └──▶ propor (LLM | heurística) ──▶ validar (padrão)
                     ▲                          │
                     └──(erros + LLM + tentativas)┤
                                                ├──(erros)──▶ reparar (heurística) ─┐
                                                └──(ok)─────────────────────────────┴─▶ finalizar

O resultado é gravado em <naming_dir>/<tabela>.json para revisão humana. Nas
próximas execuções o arquivo é a fonte da verdade: só campos novos são propostos.
O arquivo também guarda "encrypt": true/false por campo (criptografia na ingestão).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from framework.agents.transform_gen import _default_transformation
from framework.llm import get_chat_model
from framework.skills import load_skill
from framework.standards.glossary import propose_field
from framework.standards.nomenclatura import (
    RESERVED_STAGING,
    load_padroes_text,
    naturezas_table,
    validate_naming,
)
from framework.state import FrameworkState, ProfileInfo, SchemaInfo

MAX_LLM_ATTEMPTS = 3

# Substituível em testes
_chat_model_factory = get_chat_model


# ── Saída estruturada do LLM ───────────────────────────────────────────

class FieldNaming(BaseModel):
    raw_field: str = Field(description="Nome original do campo, exatamente como aparece no DDL")
    staging_field: str = Field(description="Nome padronizado: natureza_termo_qualificadores, minúsculo, sem acento, em português")
    comment: str = Field(description="Descrição clara e objetiva do campo, em português")


class NamingProposal(BaseModel):
    table_comment: str = Field(description="Descrição clara e objetiva da tabela, em português")
    fields: list[FieldNaming]


# Prompts na skill de nomenclatura (skills/nomenclatura/SKILL.md): edite lá para mudar o comportamento do LLM
_SKILL = load_skill("nomenclatura")
SYSTEM_PROMPT = _SKILL.section("Prompt do sistema")
HUMAN_PROMPT = _SKILL.section("Prompt do pedido")

NAMING_PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])


# ── Estado do subgrafo ─────────────────────────────────────────────────

class NamingState(TypedDict, total=False):
    schema: SchemaInfo
    profile: ProfileInfo | None
    llm_model: str
    naming_file: str
    dry_run: bool

    names: dict[str, dict]       # raw_field → {staging_field, comment}
    from_file: list[str]         # raw_fields definidos pelo arquivo revisado (não são reescritos)
    pending: list[str]           # raw_fields que precisam de proposta
    table_comment: str
    errors: list[dict]
    warnings: list[str]
    attempts: int
    sources: list[str]


def _fields_by_raw(schema: SchemaInfo) -> dict[str, dict]:
    return {f["raw_field"]: f for f in schema["fields"]}


def _add_source(state: NamingState, source: str) -> list[str]:
    sources = list(state.get("sources", []))
    if source not in sources:
        sources.append(source)
    return sources


# ── Nós ────────────────────────────────────────────────────────────────

def load_file_node(state: NamingState) -> NamingState:
    """Carrega nomes já revisados de <naming_dir>/<tabela>.json."""
    schema = state["schema"]
    raw_fields = [f["raw_field"] for f in schema["fields"]]
    names: dict[str, dict] = {}
    table_comment = schema.get("table_comment", "")
    sources: list[str] = []

    path = Path(state["naming_file"]) if state.get("naming_file") else None
    if path and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

        # Chave de merge do arquivo vale quando --merge-keys não foi informado
        file_keys = [k for k in data.get("merge_keys", []) if k in raw_fields]
        if file_keys and not schema.get("merge_keys"):
            schema = {**schema, "merge_keys": file_keys}

        # Transformação/formato revisados no arquivo (SDD) valem sobre o padrão por tipo
        overrides = {e["raw_field"]: e for e in data.get("fields", []) if e.get("raw_field") in raw_fields}
        if any("transformation" in e or e.get("source_format") for e in overrides.values()):
            def _with_overrides(f):
                e = overrides.get(f["raw_field"], {})
                extra = {}
                if "transformation" in e:
                    extra["transformation"] = e["transformation"]
                if e.get("source_format"):
                    extra["source_format"] = e["source_format"]
                return {**f, **extra}
            schema = {**schema, "fields": [_with_overrides(f) for f in schema["fields"]]}

        # Criptografia marcada no arquivo soma com a do --encrypt
        encrypt_from_file = {e["raw_field"] for e in data.get("fields", []) if e.get("encrypt")}
        if encrypt_from_file:
            schema = {**schema, "fields": [
                {**f, "encrypt": f.get("encrypt", False) or f["raw_field"] in encrypt_from_file}
                for f in schema["fields"]
            ]}

        for entry in data.get("fields", []):
            if entry.get("raw_field") in raw_fields and entry.get("staging_field"):
                names[entry["raw_field"]] = {
                    "staging_field": entry["staging_field"],
                    "comment": entry.get("comment", ""),
                }
        table_comment = data.get("table_comment") or table_comment
        if names:
            sources.append("arquivo")
            print(f"  Nomenclatura: {len(names)} campos carregados de {path}")

    # stagingName do data contract prevalece sobre o arquivo de revisão
    from_contract = {f["raw_field"]: f for f in schema["fields"] if f.get("contract_staging_field")}
    for raw, f in from_contract.items():
        names[raw] = {"staging_field": f["contract_staging_field"],
                      "comment": f["comment"] or names.get(raw, {}).get("comment", "")}
    if from_contract:
        sources.append("contrato")
        print(f"  Nomenclatura: {len(from_contract)} campos com stagingName do data contract")

    return {
        "schema": schema,
        "names": names,
        "from_file": list(names),
        "pending": [r for r in raw_fields if r not in names],
        "table_comment": table_comment,
        "errors": [],
        "warnings": [],
        "attempts": 0,
        "sources": sources,
    }


def _format_field_line(field: dict, profile: ProfileInfo | None) -> str:
    restrictions = []
    if field["is_pk"]:
        restrictions.append("PK")
    if field["is_fk"]:
        restrictions.append("FK")
    if not field["nullable"]:
        restrictions.append("NOT NULL")
    samples = ""
    if profile:
        pf = next((p for p in profile["fields"] if p["name"] == field["raw_field"]), None)
        if pf:
            samples = ", ".join(pf["sample_values"][:3])
    return (f"- {field['raw_field']} | {field.get('raw_type', '')} | {field['data_type']} | "
            f"{' '.join(restrictions) or '-'} | {field['comment'] or '-'} | {samples or '-'}")


def _llm_propose(state: NamingState) -> tuple[dict[str, dict], str]:
    schema = state["schema"]
    by_raw = _fields_by_raw(schema)
    pending = state["pending"]
    names = state.get("names", {})

    ja_definidos = "\n".join(
        f"- {raw} → {n['staging_field']}" for raw, n in names.items() if raw not in pending
    ) or "(nenhum)"

    erros = ""
    pending_errors = [e for e in state.get("errors", []) if e["raw_field"] in pending]
    if pending_errors:
        erros = ("A tentativa anterior foi rejeitada pela validação do padrão de nomenclatura. Corrija:\n"
                 + "\n".join(f"- {e['raw_field']}: {e['message']}" for e in pending_errors) + "\n\n")

    model = _chat_model_factory(state["llm_model"])
    chain = NAMING_PROMPT | model.with_structured_output(NamingProposal)
    result: NamingProposal = chain.invoke({
        "reservados": ", ".join(sorted(RESERVED_STAGING)),
        "naturezas": naturezas_table(),
        "padroes": load_padroes_text(),
        "source_table": schema["source_table"],
        "dataset": schema["dataset"],
        "table_comment": schema.get("table_comment") or "(nenhum)",
        "campos": "\n".join(_format_field_line(by_raw[r], state.get("profile")) for r in pending),
        "ja_definidos": ja_definidos,
        "erros": erros,
    })

    proposed = {
        f.raw_field: {"staging_field": f.staging_field.strip().lower(), "comment": f.comment.strip()}
        for f in result.fields if f.raw_field in pending
    }
    return proposed, result.table_comment


def _heuristic_propose(state: NamingState, raw_fields: list[str]) -> tuple[dict[str, dict], list[str]]:
    schema = state["schema"]
    by_raw = _fields_by_raw(schema)
    proposed: dict[str, dict] = {}
    unknown: list[str] = []
    for raw in raw_fields:
        staging, comment, unk = propose_field(by_raw[raw], schema["table_name"])
        proposed[raw] = {"staging_field": staging, "comment": comment}
        unknown.extend(u for u in unk if u not in unknown)
    warnings = []
    if unknown:
        warnings.append(f"termos mantidos sem tradução (revise no arquivo de nomenclatura): {', '.join(unknown)}")
    return proposed, warnings


def propose_node(state: NamingState) -> NamingState:
    """Propõe nomes para os campos pendentes — LLM se configurado, senão heurística."""
    names = dict(state.get("names", {}))
    warnings = list(state.get("warnings", []))
    table_comment = state.get("table_comment", "")
    attempts = state.get("attempts", 0) + 1
    llm_model = state.get("llm_model", "")

    if llm_model:
        try:
            print(f"  Nomenclatura: consultando LLM {llm_model} (tentativa {attempts}, {len(state['pending'])} campos)...")
            proposed, llm_table_comment = _llm_propose(state)
            names.update(proposed)
            table_comment = table_comment or llm_table_comment
            return {"names": names, "table_comment": table_comment, "attempts": attempts,
                    "pending": [], "sources": _add_source(state, "llm")}
        except Exception as e:  # provedor não instalado, sem chave, timeout...
            warnings.append(f"LLM indisponível ({type(e).__name__}: {e}) — usando heurística")
            print(f"  ⚠️ LLM indisponível ({type(e).__name__}) — usando heurística")
            llm_model = ""

    proposed, heuristic_warnings = _heuristic_propose(state, state["pending"])
    names.update(proposed)
    return {
        "names": names,
        "table_comment": table_comment,
        "attempts": attempts,
        "pending": [],
        "llm_model": llm_model,
        "warnings": warnings + heuristic_warnings,
        "sources": _add_source(state, "heuristica"),
    }


def validate_node(state: NamingState) -> NamingState:
    """Valida contra o padrão de nomenclatura. Campos com erro voltam para 'pending'."""
    errors, warnings = validate_naming(state["schema"]["fields"], state["names"])
    from_file = set(state.get("from_file", []))

    # Nomes do arquivo revisado são decisão humana (ex: exceção aprovada) — só avisa
    file_errors = [e for e in errors if e["raw_field"] in from_file]
    errors = [e for e in errors if e["raw_field"] not in from_file]
    warnings = [f"{e['raw_field']}: {e['message']} (definido no arquivo)" for e in file_errors] + warnings

    pending = list(dict.fromkeys(e["raw_field"] for e in errors))
    if errors:
        print(f"  Nomenclatura: {len(errors)} violações do padrão de nomenclatura em {len(pending)} campos")
    return {"errors": errors, "pending": pending, "warnings": _merge(state.get("warnings", []), warnings)}


def _merge(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))


def repair_node(state: NamingState) -> NamingState:
    """Último recurso: heurística nos campos que continuam inválidos + desduplicação."""
    names = dict(state["names"])
    proposed, heuristic_warnings = _heuristic_propose(state, state["pending"])
    names.update(proposed)

    # Garante unicidade (não mexe nos campos do arquivo)
    from_file = set(state.get("from_file", []))
    used = {n["staging_field"] for raw, n in names.items() if raw in from_file}
    for raw in [f["raw_field"] for f in state["schema"]["fields"]]:
        if raw in from_file or raw not in names:
            continue
        staging = names[raw]["staging_field"]
        base, i = staging, 2
        while staging in used or staging in RESERVED_STAGING:
            staging = f"{base}_{i}"
            i += 1
        names[raw] = {**names[raw], "staging_field": staging}
        used.add(staging)

    warnings = _merge(state.get("warnings", []), heuristic_warnings)
    warnings.append(f"campos reparados por heurística (revise): {', '.join(state['pending'])}")
    return {"names": names, "pending": [], "warnings": warnings, "sources": _add_source(state, "heuristica")}


def finalize_node(state: NamingState) -> NamingState:
    """Aplica os nomes no schema e grava o arquivo revisável."""
    schema = state["schema"]
    names = state["names"]

    errors, _ = validate_naming(schema["fields"], names)
    warnings = _merge(state.get("warnings", []), [f"{e['raw_field']}: {e['message']}" for e in errors])

    fields = []
    for f in schema["fields"]:
        n = names.get(f["raw_field"], {})
        fields.append({
            **f,
            "staging_field": n.get("staging_field") or f["raw_field"],
            "comment": n.get("comment") or f["comment"],
        })
    table_comment = state.get("table_comment") or f"Tabela {schema['table_name']} do dataset {schema['dataset']}."
    new_schema = {**schema, "fields": fields, "table_comment": table_comment}

    if state.get("naming_file") and not state.get("dry_run"):
        profile = state.get("profile")
        monetary_raw = set(profile.get("monetary_fields", [])) if profile else set()
        path = Path(state["naming_file"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "table": schema["table_name"],
            "source_table": schema["source_table"],
            "table_comment": table_comment,
            "merge_keys": schema.get("merge_keys", []),
            "fields": [
                {"raw_field": f["raw_field"], "staging_field": f["staging_field"],
                 "data_type": f["data_type"], "comment": f["comment"], "encrypt": f.get("encrypt", False),
                 "transformation": (f["transformation"] if "transformation" in f
                                    else _default_transformation(f, monetary_raw)),
                 "source_format": f.get("source_format", "")}
                for f in fields
            ],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  Nomenclatura gravada em {path} (edite e rode de novo para ajustar)")

    return {"schema": new_schema, "warnings": warnings}


# ── Roteamento ─────────────────────────────────────────────────────────

def _route_after_load(state: NamingState) -> str:
    return "propor" if state["pending"] else "validar"


def _route_after_validate(state: NamingState) -> str:
    if not state["errors"]:
        return "finalizar"
    if state.get("llm_model") and state.get("attempts", 0) < MAX_LLM_ATTEMPTS:
        return "propor"
    return "reparar"


def build_naming_graph():
    graph = StateGraph(NamingState)
    graph.add_node("carregar_arquivo", load_file_node)
    graph.add_node("propor", propose_node)
    graph.add_node("validar", validate_node)
    graph.add_node("reparar", repair_node)
    graph.add_node("finalizar", finalize_node)

    graph.add_edge(START, "carregar_arquivo")
    graph.add_conditional_edges("carregar_arquivo", _route_after_load, {"propor": "propor", "validar": "validar"})
    graph.add_edge("propor", "validar")
    graph.add_conditional_edges("validar", _route_after_validate, {
        "propor": "propor",
        "reparar": "reparar",
        "finalizar": "finalizar",
    })
    graph.add_edge("reparar", "finalizar")
    graph.add_edge("finalizar", END)
    return graph.compile()


# ── Agente do grafo principal ──────────────────────────────────────────

def naming_file_for(naming_dir: str, table_name: str) -> str:
    return str(Path(naming_dir) / f"{table_name}.json") if naming_dir else ""


def naming_agent(state: FrameworkState) -> FrameworkState:
    """Agente de Nomenclatura: schema com staging_field/comment no padrão de nomenclatura."""
    print("[Agente Nomenclatura] Aplicando padrão de nomenclatura...")
    schema = state["schema"]

    result = build_naming_graph().invoke({
        "schema": schema,
        "profile": state.get("profile"),
        "llm_model": state.get("llm_model", ""),
        "naming_file": naming_file_for(state.get("naming_dir", ""), schema["table_name"]),
        "dry_run": state.get("dry_run", False),
    })

    for w in result.get("warnings", []):
        print(f"  ⚠️ {w}")
    source = "+".join(result.get("sources", [])) or "arquivo"
    print(f"[Agente Nomenclatura] Concluído (fonte: {source}).")

    return {
        "schema": result["schema"],
        "naming_source": source,
        "naming_warnings": result.get("warnings", []),
    }

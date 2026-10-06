"""Agente 1 — Profiler.

Não usa LLM. Faz parse do DDL e profiling da amostra de forma determinística.
Responsabilidade: DDL + amostra → schema + profile.
"""

from __future__ import annotations

from framework.state import FrameworkState
from framework.parsers.contract_parser import contract_to_schema, load_contract, resolve_table
from framework.parsers.ddl_parser import parse_ddl
from framework.parsers.sample_profiler import looks_like_pii_name, profile_sample
from framework.standards.sources import get_source
from framework.standards.tipagem import load_type_map


def profiler_agent(state: FrameworkState) -> FrameworkState:
    """Agente 1: analisa DDL + amostra e produz schema + profile.

    Não precisa de LLM — é tudo determinístico (parser + estatística).
    """
    print("[Agente 1 — Profiler] Iniciando análise...")

    # Tipagem: ajustes do banco de origem + planilha Tipagem.xlsx (se informada, prevalece)
    source = get_source(state.get("source_db", "postgres"))
    type_map = dict(source.type_overrides)
    if state.get("tipagem_path"):
        xlsx_map = load_type_map(state["tipagem_path"])
        type_map.update(xlsx_map)
        print(f"  Tipagem: {len(xlsx_map)} mapeamentos de {state['tipagem_path']}")
    print(f"  Banco de origem: {source.name}")

    # Parse do contrato (ODCS) ou do DDL
    if state.get("contract"):
        ct = resolve_table(load_contract(state["contract"]), state.get("contract_table", ""))
        schema = contract_to_schema(ct, dataset=state.get("dataset") or "dataset", type_map=type_map)
        print(f"  Data contract: {ct.contract.get('id', '(sem id)')} v{ct.contract.get('version', '?')}")
    else:
        schema = parse_ddl(state["ddl"], dataset=state.get("dataset") or "dataset", type_map=type_map)
    print(f"  Schema: {schema['table_name']} ({len(schema['fields'])} campos)")
    print(f"  PK: {schema['pk_fields']}")
    print(f"  Source table: {schema['source_table']}")

    # Coluna de partição (--partition-col): precisa existir e ser data/timestamp
    partition_col = (state.get("partition_col") or "").strip()
    if partition_col:
        match = next((f for f in schema["fields"] if f["raw_field"].lower() == partition_col.lower()), None)
        if match is None:
            raise ValueError(f"--partition-col: coluna '{partition_col}' não existe no DDL")
        if match["data_type"] not in ("DateType", "TimestampType"):
            raise ValueError(f"--partition-col: coluna '{match['raw_field']}' é {match['data_type']}; "
                             f"precisa ser data/timestamp")
        schema["partition_column"] = match["raw_field"]
        print(f"  Coluna de partição: {match['raw_field']}")

    # Chave de merge do Delta (--merge-keys): colunas precisam existir no DDL
    merge_keys = [c.strip() for c in state.get("merge_keys", []) if c.strip()]
    if merge_keys:
        by_lower = {f["raw_field"].lower(): f["raw_field"] for f in schema["fields"]}
        unknown_keys = [c for c in merge_keys if c.lower() not in by_lower]
        if unknown_keys:
            raise ValueError(f"--merge-keys: colunas inexistentes no DDL: {', '.join(unknown_keys)}")
        schema["merge_keys"] = list(dict.fromkeys(by_lower[c.lower()] for c in merge_keys))
        print(f"  Chave de merge: {schema['merge_keys']}")

    # Colunas a criptografar na ingestão (--encrypt)
    encrypt = {c.strip().lower() for c in state.get("encrypt_columns", []) if c.strip()}
    raw_names = {f["raw_field"].lower() for f in schema["fields"]}
    unknown = encrypt - raw_names
    if unknown:
        raise ValueError(f"--encrypt: colunas inexistentes no DDL: {', '.join(sorted(unknown))}")
    for f in schema["fields"]:
        f["encrypt"] = f["raw_field"].lower() in encrypt
    if encrypt:
        print(f"  Criptografia: {sorted(encrypt)}")

    # Profiling da amostra
    profile = None
    if state.get("sample_path"):
        profile = profile_sample(state["sample_path"])
        print(f"  Amostra: {profile['row_count']} linhas")
        if profile["has_monetary_fields"]:
            print(f"  Campos monetários (centavos): {profile['monetary_fields']}")

    # Aviso LGPD: colunas que parecem sensíveis e não serão criptografadas
    pii_fields = {f["name"].lower() for f in profile["fields"] if f["looks_like_pii"]} if profile else set()
    pii_fields |= {f["raw_field"].lower() for f in schema["fields"] if looks_like_pii_name(f["raw_field"])}
    not_encrypted = sorted(pii_fields & raw_names - encrypt)
    if not_encrypted:
        print(f"  ⚠️ Possível dado sensível sem criptografia (use --encrypt): {not_encrypted}")

    print("[Agente 1 — Profiler] Concluído.")

    return {
        **state,
        "schema": schema,
        "profile": profile,
        "status": "generating",
    }

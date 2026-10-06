"""Agente 2 — Input Gen.

Gera o ingestion.yml (ingestion/v1) lido pelo ingestion-orchestrator, a partir do schema + data contract.
"""

from __future__ import annotations

from framework.ingestion_config import build_ingestion_config, dump_ingestion_config, placeholders
from framework.state import FrameworkState

INGESTION_CONFIG_DIR = "ingestion-config"


def ingestion_config_path(dataset: str, table_name: str) -> str:
    return f"{INGESTION_CONFIG_DIR}/{dataset}/{table_name}.ingestion.yml"


def _infer_date_columns(schema: dict) -> tuple[str, str]:
    """Colunas de data do filtro incremental: (principal, atualização).

    --partition-col / partitioned: true tem prioridade; senão procura created_at/updated_at.
    """
    if schema.get("partition_column"):
        return schema["partition_column"], schema["partition_column"]

    field_names = {f["raw_field"] for f in schema["fields"]}
    date_col = "created_at" if "created_at" in field_names else ""
    date_col_updated = "updated_at" if "updated_at" in field_names else ""

    # Fallback: primeiros campos de timestamp com created/updated no nome
    if not date_col:
        for f in schema["fields"]:
            if f["data_type"] == "TimestampType" and "created" in f["raw_field"].lower():
                date_col = f["raw_field"]
                break
    if not date_col_updated:
        for f in schema["fields"]:
            if f["data_type"] == "TimestampType" and "updated" in f["raw_field"].lower():
                date_col_updated = f["raw_field"]
                break

    return date_col, date_col_updated or date_col


def input_gen_agent(state: FrameworkState) -> FrameworkState:
    """Agente 2: gera o ingestion.yml."""
    if state.get("skip_input", False):
        print("[Agente 2 — Input Gen] Pulando geração do ingestion.yml (--skip-input).")
        return {"input_files": {}, "input_project_dir": ""}

    print("[Agente 2 — Input Gen] Gerando ingestion.yml...")
    schema = state["schema"]
    date_col, date_col_updated = _infer_date_columns(schema)
    config = build_ingestion_config(
        schema,
        partition_col=date_col,
        extra_incremental=[date_col_updated] if date_col_updated and date_col_updated != date_col else [],
        source_db=state.get("source_db", "postgres"),
        contract_text=state.get("contract", ""),
        contract_table=state.get("contract_table", ""),
    )
    path = ingestion_config_path(schema["dataset"], schema["table_name"])

    print(f"  {path}")
    print(f"  Origem: {config['source']['type']} {config['source']['table']} "
          f"(ambientes: {', '.join(config['source']['servers'])})")
    print(f"  Carga: {config['load']['mode']}"
          + (f" por {', '.join(config['load']['incrementalColumns'])}" if config["load"]["incrementalColumns"] else ""))
    if config.get("encryption"):
        print(f"  Criptografia: {config['encryption']['columns']}")
    if config.get("quality"):
        print(f"  Qualidade: {len(config['quality'])} regras")
    pending = placeholders(config)
    if pending:
        print(f"  ⚠️ Campos a preencher no contrato (estão como PREENCHER): {', '.join(pending)}")

    print("[Agente 2 — Input Gen] Concluído.")
    return {"input_files": {path: dump_ingestion_config(config)}, "input_project_dir": INGESTION_CONFIG_DIR}

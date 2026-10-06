"""Agente 3 — Transform Gen.

Gera o projeto Scala de transformação no padrão heavy-transformation definido
pelas skills de transformação:

    src/main/scala/br/com/datalake/
      Main.scala                          ← --table_name seleciona o processor
      error/SparkErrorHandler.scala
      processor/<tabela>/<Tabela>Model.scala      ← FieldSpec, merge keys, partições
      processor/<tabela>/<Tabela>Processor.scala  ← fluxo canônico (read → ... → Hive)
      utils/                              ← scripts das skills (1:1)
    docs_sdd/<tabela>_sdd_doc.md          ← SDD (10 seções)
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from framework.repo import DEFAULT_GITHUB_ORG, repo_files
from framework.state import FrameworkState
from framework.utils import scala_identifier

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "transformation"
STATIC_DIR = TEMPLATES_DIR / "static"

PARTITION_UPDATE = "dt_atualizacao_registro_particao"
TIMESTAMP_FIELD = "dh_criacao_data_lake"

# Tamanho estimado (bytes) por tipo, para o file sizing da primeira carga
_TYPE_SIZE = {"StringType": 32, "IntegerType": 4, "LongType": 8, "ShortType": 2, "ByteType": 1,
              "DoubleType": 8, "FloatType": 4, "BooleanType": 1, "DateType": 4, "TimestampType": 8}


def _template_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _pascal(name: str) -> str:
    """forecast_produto → ForecastProduto"""
    return "".join(p.capitalize() for p in re.split(r"[^A-Za-z0-9]+", name) if p)


def _package(table_name: str) -> str:
    """Nome do pacote Scala da tabela (minúsculo, identificador válido)."""
    pkg = re.sub(r"[^a-z0-9_]", "_", table_name.lower())
    return f"t_{pkg}" if pkg[:1].isdigit() else pkg


def _scala_str(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace('"', "'")


# ── Campos ─────────────────────────────────────────────────────────────

def _default_transformation(f: dict, monetary_raw: set[str]) -> str | None:
    """Transformação padrão do SDD por tipo (data-transformation-patterns)."""
    if f.get("encrypt"):
        return None  # já criptografado na ingestão — preservar
    if f["raw_field"] in monetary_raw:
        return "centavos"
    dt = f["data_type"]
    if dt.startswith("ArrayType"):
        return None
    if dt == "StringType":
        nat = f["staging_field"].split("_", 1)[0]
        # Identificadores preservam o case (uuid, chaves técnicas)
        if nat == "id" or (f.get("raw_type") or "").lower().startswith("uuid"):
            return None
        # Data/hora guardada como texto: nunca TRIM+UPPER (timestamp-handling)
        if nat in ("dt", "dh", "hr"):
            return None
    return "default"


def _field_specs(schema: dict, profile: dict | None) -> list[dict]:
    monetary_raw = set(profile.get("monetary_fields", [])) if profile else set()
    specs = []
    for f in schema["fields"]:
        data_type = f["data_type"]
        if f.get("encrypt") or data_type.startswith("ArrayType"):
            data_type = "StringType"  # chega na raw como texto (base64 / JSON)

        # Override do arquivo de nomenclatura ("transformation": "default" | "format" | null)
        if "transformation" in f:
            transformation = f["transformation"] or None
        else:
            transformation = _default_transformation(f, monetary_raw)

        comment = _scala_str(f["comment"])
        args = [f'"{f["raw_field"].lower()}"', f'"{f["staging_field"]}"', data_type, f'"{comment}"']
        if f.get("encrypt"):
            args.append("encrypted = true")
        if f.get("source_format"):
            args.append(f'sourceFormat = Some("{f["source_format"]}")')
        args.append(f'transformation = Some("{transformation}")' if transformation else "transformation = None")

        specs.append({
            "source": f["raw_field"].lower(),  # a ingestão grava as colunas em minúsculo
            "target": f["staging_field"],
            "data_type": data_type,
            "comment": comment,
            "encrypted": bool(f.get("encrypt")),
            "source_format": f.get("source_format") or "",
            "transformation": transformation,
            "args": ", ".join(args),
        })

    # Coluna de controle vinda da ingestão ("@timestamp" = CURRENT_TIMESTAMP da query)
    specs.append({
        "source": "@timestamp", "target": TIMESTAMP_FIELD, "data_type": "TimestampType",
        "comment": "Data e horario da criacao do registro no Data Lake.", "encrypted": False,
        "source_format": "", "transformation": "default",
        "args": f'"@timestamp", "{TIMESTAMP_FIELD}", TimestampType, '
                f'"Data e horario da criacao do registro no Data Lake.", transformation = Some("default")',
    })
    return specs


def _merge_keys(schema: dict) -> tuple[list[str], str]:
    """Chave de merge (staging): --merge-keys > PK do DDL > primeiro campo não-nulo."""
    by_raw = {f["raw_field"]: f for f in schema["fields"]}
    if schema.get("merge_keys"):
        return [by_raw[k]["staging_field"] for k in schema["merge_keys"]], "--merge-keys"
    if schema.get("pk_fields"):
        return [by_raw[k]["staging_field"] for k in schema["pk_fields"] if k in by_raw], "PK do DDL"
    for f in schema["fields"]:
        if not f["nullable"] and f["data_type"] in ("StringType", "IntegerType", "LongType"):
            print(f"  ⚠️ Sem PK nem --merge-keys: merge só por '{f['raw_field']}'. "
                  f"Se não for único, registros serão sobrescritos — informe --merge-keys")
            return [f["staging_field"]], "heurística"
    raise ValueError(
        f"Transformação de '{schema['table_name']}': sem PK no DDL e sem coluna NOT NULL para a chave de merge. "
        f"Informe --merge-keys (ex: --merge-keys {schema['fields'][0]['raw_field']})")


def _partition_source(schema: dict) -> tuple[dict | None, bool]:
    """Campo de data que origina a partição de dados (L1). Retorna (campo, inferido?)."""
    dated = [f for f in schema["fields"] if f["data_type"] in ("DateType", "TimestampType") and not f.get("encrypt")]
    by_raw = {f["raw_field"]: f for f in dated}
    if schema.get("partition_column") in by_raw:
        return by_raw[schema["partition_column"]], False
    for f in dated:
        if f["raw_field"].lower() == "created_at" or "created" in f["raw_field"].lower():
            return f, True
    return (dated[0], True) if dated else (None, False)


def _partitions(source: dict | None) -> list[dict]:
    parts = []
    if source:
        term = source["staging_field"].split("_", 1)[1]
        parts.append({
            "name": f"dt_{term}_particao",
            "expression": f'date_format(col("{source["staging_field"]}"), "yyyyMMdd")',
            "comment": f"Data de {term.replace('_', ' ')} (yyyyMMdd) - particao de dados.",
        })
    parts.append({
        "name": PARTITION_UPDATE,
        "expression": "lit(runDateYyyymmdd)",
        "comment": "Data de processamento (yyyyMMdd) - particao de atualizacao.",
    })
    return parts


def _avg_row_size(specs: list[dict]) -> int:
    size = 40  # rastreabilidade + partições + overhead
    for s in specs:
        dt = s["data_type"]
        size += 16 if dt.startswith("DecimalType") else _TYPE_SIZE.get(dt, 32)
    return max(size, 64)


def render_field_block(schema: dict) -> str:
    """Bloco `object Field` no formato ModelField (comando `campos`)."""
    lines = ["object Field {"]
    for f in schema["fields"]:
        comment = _scala_str(f["comment"])
        data_type = f["data_type"]
        if f.get("encrypt"):
            data_type = "StringType"
            comment = f"{comment.rstrip('.')} (criptografado AES/ECB, base64)."
        lines.append(
            f'  final val {scala_identifier(f["staging_field"])} = ModelField(rawField = "{f["raw_field"].lower()}", '
            f'stagingField = "{f["staging_field"]}", dataType = {data_type}, comment = "{comment}")'
        )
    lines.append("}")
    return "\n".join(lines)


# ── Agente ─────────────────────────────────────────────────────────────

def transform_gen_agent(state: FrameworkState) -> FrameworkState:
    """Agente 3: gera o projeto Scala de transformação (padrão das skills)."""
    print("[Agente 3 — Transform Gen] Gerando projeto de transformação...")

    schema = state["schema"]
    env = _template_env()

    table_name = schema["table_name"]
    dataset = schema["dataset"]
    pkg = _package(table_name)
    model = f"{_pascal(table_name)}Model"
    processor = f"{_pascal(table_name)}Processor"

    specs = _field_specs(schema, state.get("profile"))
    merge_keys, merge_keys_source = _merge_keys(schema)
    partition_source, partition_inferred = _partition_source(schema)
    partitions = _partitions(partition_source)
    table_comment = _scala_str(schema.get("table_comment") or f"Tabela {table_name} do dataset {dataset}.")
    avg_row_size = _avg_row_size(specs)

    ctx = dict(
        dataset=dataset, database=dataset, table_name=table_name, table_comment=table_comment,
        package=pkg, model=model, processor=processor, fields=specs, merge_keys=merge_keys,
        merge_keys_source=merge_keys_source, partitions=partitions, timestamp_field=TIMESTAMP_FIELD,
        avg_row_size=avg_row_size, source_table=schema["source_table"],
        source_db=state.get("source_db") or "postgres",
        partition_inferred=partition_inferred,
        partition_source_raw=partition_source["raw_field"] if partition_source else "",
        encrypted=[s for s in specs if s["encrypted"]],
        cents=[s for s in specs if s["transformation"] == "centavos"],
    )

    project_name = f"{dataset}-transformation"
    scala = f"{project_name}/src/main/scala/br/com/datalake"
    new_files = {
        f"{project_name}/build.sbt": env.get_template("build.sbt.j2").render(dataset=dataset),
        f"{project_name}/project/plugins.sbt": env.get_template("plugins.sbt.j2").render(),
        f"{project_name}/project/build.properties": env.get_template("build.properties.j2").render(),
        f"{project_name}/docs_sdd/{table_name}_sdd_doc.md": env.get_template("sdd_doc.md.j2").render(**ctx),
        f"{scala}/processor/{pkg}/{model}.scala": env.get_template("Model.scala.j2").render(**ctx),
        f"{scala}/processor/{pkg}/{processor}.scala": env.get_template("Processor.scala.j2").render(**ctx),
    }

    # Utilitários das skills (cópia 1:1) + error handler
    for static_file in sorted(STATIC_DIR.rglob("*.scala")):
        rel = static_file.relative_to(STATIC_DIR).as_posix()
        new_files[f"{scala}/{rel}"] = static_file.read_text(encoding="utf-8")

    # Arquivos de repositório (pipeline GitHub → CodeCommit, Backstage, .gitignore)
    new_files.update(repo_files(
        project_name,
        codecommit_repo=state.get("codecommit_transformation") or f"{dataset}-transformation",
        github_org=state.get("github_org") or DEFAULT_GITHUB_ORG,
    ))

    # Acumula com arquivos já existentes (--append) — várias tabelas no mesmo projeto
    existing_files = state.get("transform_files", {})
    all_files = {**existing_files, **new_files}

    # Main.scala com todas as tabelas do projeto
    model_re = re.compile(r"/processor/([^/]+)/([A-Za-z0-9]+)Model\.scala$")
    models = []
    for fp in sorted(all_files):
        m = model_re.search(fp)
        if m:
            models.append({"package": m.group(1), "model": f"{m.group(2)}Model", "processor": f"{m.group(2)}Processor"})
    all_files[f"{scala}/Main.scala"] = env.get_template("Main.scala.j2").render(dataset=dataset, models=models)

    print(f"  Gerados {len(new_files) + 1} arquivos para {project_name}")
    print(f"  Model: {model} ({len(specs)} campos) — Processor: {processor}")
    print(f"  Merge keys: {merge_keys} ({merge_keys_source})")
    print(f"  Partições: {[p['name'] for p in partitions]}")
    if ctx["cents"]:
        print(f"  Campos em centavos (/100): {[s['target'] for s in ctx['cents']]}")
    if len(models) > 1:
        print(f"  Tabelas no projeto: {[m['model'] for m in models]}")
    print(f"  SDD: docs_sdd/{table_name}_sdd_doc.md (revise as seções pendentes)")

    print("[Agente 3 — Transform Gen] Concluído.")

    return {
        "transform_files": all_files,
        "transform_project_dir": project_name,
    }

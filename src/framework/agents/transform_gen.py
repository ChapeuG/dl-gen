"""Agente 3 — Transform Gen.

Gera o projeto de transformação no padrão heavy-transformation definido pelas
skills de transformação, em PySpark (padrão) ou Scala (state["language"]):

PySpark:
    main.py                               ← --table_name seleciona o processor
    pyproject.toml
    datalake/
      error/spark_error_handler.py
      processor/<tabela>/<tabela>_model.py      ← FieldSpec, merge keys, partições
      processor/<tabela>/<tabela>_processor.py  ← fluxo canônico (read → ... → Hive)
      utils/                              ← scripts das skills (1:1)

Scala (sbt):
    build.sbt, project/
    src/main/scala/br/com/datalake/
      Main.scala, error/SparkErrorHandler.scala
      processor/<tabela>/<Tabela>Model.scala, <Tabela>Processor.scala
      utils/

Nas duas: docs_sdd/<tabela>_sdd_doc.md    ← SDD (10 seções)
"""

from __future__ import annotations

import keyword
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from framework.repo import DEFAULT_GITHUB_ORG, repo_files
from framework.state import FrameworkState
from framework.utils import scala_identifier

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "transformation"

LANGUAGES = ("pyspark", "scala")
DEFAULT_LANGUAGE = "pyspark"

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


def resolve_language(language: str | None) -> str:
    lang = (language or DEFAULT_LANGUAGE).strip().lower()
    if lang not in LANGUAGES:
        raise ValueError(f"Linguagem da transformação '{language}' inválida: use {' ou '.join(LANGUAGES)}")
    return lang


def _package(table_name: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Nome do pacote da tabela (minúsculo, identificador válido)."""
    pkg = re.sub(r"[^a-z0-9_]", "_", table_name.lower())
    if pkg[:1].isdigit():
        return f"t_{pkg}"
    return f"{pkg}_" if language == "pyspark" and keyword.iskeyword(pkg) else pkg


def _split_args(args: str) -> list[str]:
    """Separa argumentos no nível de topo: "StringType,DecimalType(1,2)" → ["StringType", "DecimalType(1,2)"]."""
    parts, depth, cur = [], 0, ""
    for ch in args:
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _py_type(data_type: str) -> str:
    """Tipo Spark do schema → construtor PySpark: StringType → StringType(), DecimalType(12,2) → DecimalType(12, 2)."""
    name, _, rest = data_type.partition("(")
    args = _split_args(rest[:-1]) if rest.endswith(")") else []
    py_args = [_py_type(a) if a[:1].isupper() else a for a in args]
    return f"{name.strip()}({', '.join(py_args)})"


def _str_literal(text: str) -> str:
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


def _spec_args(source: str, target: str, data_type: str, comment: str, encrypted: bool,
               source_format: str, transformation: str | None, language: str) -> str:
    """Argumentos do FieldSpec na sintaxe da linguagem."""
    if language == "scala":
        args = [f'"{source}"', f'"{target}"', data_type, f'"{comment}"']
        if encrypted:
            args.append("encrypted = true")
        if source_format:
            args.append(f'sourceFormat = Some("{source_format}")')
        args.append(f'transformation = Some("{transformation}")' if transformation else "transformation = None")
    else:
        args = [f'"{source}"', f'"{target}"', _py_type(data_type), f'"{comment}"']
        if encrypted:
            args.append("encrypted=True")
        if source_format:
            args.append(f'source_format="{source_format}"')
        args.append(f'transformation="{transformation}"' if transformation else "transformation=None")
    return ", ".join(args)


def _field_specs(schema: dict, profile: dict | None, language: str = DEFAULT_LANGUAGE) -> list[dict]:
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

        comment = _str_literal(f["comment"])

        specs.append({
            "source": f["raw_field"].lower(),  # a ingestão grava as colunas em minúsculo
            "target": f["staging_field"],
            "data_type": data_type,
            "comment": comment,
            "encrypted": bool(f.get("encrypt")),
            "source_format": f.get("source_format") or "",
            "transformation": transformation,
            "args": _spec_args(f["raw_field"].lower(), f["staging_field"], data_type, comment,
                               bool(f.get("encrypt")), f.get("source_format") or "", transformation, language),
        })

    # Coluna de controle vinda da ingestão ("@timestamp" = CURRENT_TIMESTAMP da query)
    specs.append({
        "source": "@timestamp", "target": TIMESTAMP_FIELD, "data_type": "TimestampType",
        "comment": "Data e horario da criacao do registro no Data Lake.", "encrypted": False,
        "source_format": "", "transformation": "default",
        "args": _spec_args("@timestamp", TIMESTAMP_FIELD, "TimestampType",
                           "Data e horario da criacao do registro no Data Lake.", False, "", "default", language),
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


def _partitions(source: dict | None, language: str = DEFAULT_LANGUAGE) -> list[dict]:
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
        "expression": "lit(runDateYyyymmdd)" if language == "scala" else "lit(run_date_yyyymmdd)",
        "comment": "Data de processamento (yyyyMMdd) - particao de atualizacao.",
    })
    return parts


def _avg_row_size(specs: list[dict]) -> int:
    size = 40  # rastreabilidade + partições + overhead
    for s in specs:
        dt = s["data_type"]
        size += 16 if dt.startswith("DecimalType") else _TYPE_SIZE.get(dt, 32)
    return max(size, 64)


def render_field_block(schema: dict, profile: dict | None = None, language: str = DEFAULT_LANGUAGE) -> str:
    """Bloco de campos para colar num model (comando `campos`).

    PySpark: lista `fields` de FieldSpec. Scala: `object Field` no formato ModelField.
    """
    if resolve_language(language) == "scala":
        lines = ["object Field {"]
        for f in schema["fields"]:
            comment = _str_literal(f["comment"])
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

    lines = ["fields = ["]
    for spec in _field_specs(schema, profile)[:-1]:  # sem a coluna de controle @timestamp
        lines.append(f"    FieldSpec({spec['args']}),")
    lines.append("]")
    return "\n".join(lines)


# ── Agente ─────────────────────────────────────────────────────────────

def _pyspark_files(env: Environment, ctx: dict, project_name: str) -> dict[str, str]:
    pkg = ctx["package"]
    code = f"{project_name}/datalake"
    files = {
        f"{project_name}/pyproject.toml": env.get_template("pyspark/pyproject.toml.j2").render(**ctx),
        f"{code}/processor/{pkg}/{pkg}_model.py": env.get_template("pyspark/model.py.j2").render(**ctx),
        f"{code}/processor/{pkg}/{pkg}_processor.py": env.get_template("pyspark/processor.py.j2").render(**ctx),
    }
    for package_dir in ("", "/error", "/utils", "/processor", f"/processor/{pkg}"):
        files[f"{code}{package_dir}/__init__.py"] = ""
    static_dir = TEMPLATES_DIR / "pyspark" / "static"
    for static_file in sorted(static_dir.rglob("*.py")):
        files[f"{code}/{static_file.relative_to(static_dir).as_posix()}"] = static_file.read_text(encoding="utf-8")
    return files


def _pyspark_main(env: Environment, all_files: dict[str, str], project_name: str, dataset: str) -> tuple[str, list]:
    path_re = re.compile(r"/processor/([^/]+)/\1_model\.py$")
    class_re = re.compile(r"^class (\w+)\(TableModel\):", re.MULTILINE)
    models = []
    for fp in sorted(all_files):
        m = path_re.search(fp)
        cls = class_re.search(all_files[fp]) if m else None
        if cls:
            models.append({"package": m.group(1), "model": cls.group(1)})
    return f"{project_name}/main.py", env.get_template("pyspark/main.py.j2").render(dataset=dataset, models=models), models


def _scala_files(env: Environment, ctx: dict, project_name: str) -> dict[str, str]:
    pkg, model, processor = ctx["package"], ctx["model"], ctx["processor"]
    scala = f"{project_name}/src/main/scala/br/com/datalake"
    files = {
        f"{project_name}/build.sbt": env.get_template("scala/build.sbt.j2").render(**ctx),
        f"{project_name}/project/plugins.sbt": env.get_template("scala/plugins.sbt.j2").render(),
        f"{project_name}/project/build.properties": env.get_template("scala/build.properties.j2").render(),
        f"{scala}/processor/{pkg}/{model}.scala": env.get_template("scala/Model.scala.j2").render(**ctx),
        f"{scala}/processor/{pkg}/{processor}.scala": env.get_template("scala/Processor.scala.j2").render(**ctx),
    }
    static_dir = TEMPLATES_DIR / "scala" / "static"
    for static_file in sorted(static_dir.rglob("*.scala")):
        files[f"{scala}/{static_file.relative_to(static_dir).as_posix()}"] = static_file.read_text(encoding="utf-8")
    return files


def _scala_main(env: Environment, all_files: dict[str, str], project_name: str, dataset: str) -> tuple[str, list]:
    model_re = re.compile(r"/processor/([^/]+)/([A-Za-z0-9]+)Model\.scala$")
    models = []
    for fp in sorted(all_files):
        m = model_re.search(fp)
        if m:
            models.append({"package": m.group(1), "model": f"{m.group(2)}Model", "processor": f"{m.group(2)}Processor"})
    path = f"{project_name}/src/main/scala/br/com/datalake/Main.scala"
    return path, env.get_template("scala/Main.scala.j2").render(dataset=dataset, models=models), models


def transform_gen_agent(state: FrameworkState) -> FrameworkState:
    """Agente 3: gera o projeto de transformação (padrão das skills) em PySpark ou Scala."""
    language = resolve_language(state.get("language"))
    print(f"[Agente 3 — Transform Gen] Gerando projeto de transformação ({language})...")

    schema = state["schema"]
    env = _template_env()

    table_name = schema["table_name"]
    dataset = schema["dataset"]
    pkg = _package(table_name, language)
    model = f"{_pascal(table_name)}Model"
    processor = f"{_pascal(table_name)}Processor" if language == "scala" else f"{pkg}_processor.process"

    specs = _field_specs(schema, state.get("profile"), language)
    merge_keys, merge_keys_source = _merge_keys(schema)
    partition_source, partition_inferred = _partition_source(schema)
    partitions = _partitions(partition_source, language)
    table_comment = _str_literal(schema.get("table_comment") or f"Tabela {table_name} do dataset {dataset}.")
    avg_row_size = _avg_row_size(specs)

    type_imports = sorted({t for spec in specs for t in re.findall(r"\b([A-Z]\w*Type)\(", spec["args"])})

    ctx = dict(
        language=language, dataset=dataset, database=dataset, table_name=table_name, table_comment=table_comment,
        package=pkg, model=model, processor=processor, type_imports=type_imports, fields=specs,
        merge_keys=merge_keys,
        merge_keys_source=merge_keys_source, partitions=partitions, timestamp_field=TIMESTAMP_FIELD,
        avg_row_size=avg_row_size, source_table=schema["source_table"],
        source_db=state.get("source_db") or "postgres",
        partition_inferred=partition_inferred,
        partition_source_raw=partition_source["raw_field"] if partition_source else "",
        encrypted=[s for s in specs if s["encrypted"]],
        cents=[s for s in specs if s["transformation"] == "centavos"],
        relationships=[{"raw": f["raw_field"], "staging": f["staging_field"], "to": f["references"]}
                       for f in schema["fields"] if f.get("references")],
    )

    project_name = f"{dataset}-transformation"
    build_files, build_main = (_scala_files, _scala_main) if language == "scala" else (_pyspark_files, _pyspark_main)
    new_files = {
        f"{project_name}/docs_sdd/{table_name}_sdd_doc.md": env.get_template("sdd_doc.md.j2").render(**ctx),
        **build_files(env, ctx, project_name),
    }

    # Arquivos de repositório (pipeline GitHub → CodeCommit, Backstage, .gitignore)
    new_files.update(repo_files(
        project_name,
        codecommit_repo=state.get("codecommit_transformation") or f"{dataset}-transformation",
        github_org=state.get("github_org") or DEFAULT_GITHUB_ORG,
        language=language,
    ))

    # Acumula com arquivos já existentes (--append) — várias tabelas no mesmo projeto
    existing_files = state.get("transform_files", {})
    all_files = {**existing_files, **new_files}

    # Entry point com todas as tabelas do projeto
    main_path, main_content, models = build_main(env, all_files, project_name, dataset)
    all_files[main_path] = main_content

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

"""CLI — interface de linha de comando do framework.

Uso:
    dl-gen generate --contract actor.odcs.yaml                      # ingestion.yml + transformação
    dl-gen generate --ddl schema.sql --sample data.csv --dataset vendas
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from framework.agents.transform_gen import resolve_language
from framework.graph import build_graph
from framework.llm import DEFAULT_MODEL_ENV, resolve_model_name
from framework.parsers.schema_reader import read_schema
from framework.parsers.contract_parser import check_relationships, custom_props, load_contract, resolve_table
from framework.standards.sources import SOURCES
from framework.state import FrameworkState

console = Console()


@click.group()
def main():
    """Data Lake Generator — gera o ingestion.yml e o projeto de transformação (PySpark ou Scala) a partir do data contract."""
    pass


def naming_options(f):
    """Opções compartilhadas de nomenclatura e tipagem."""
    f = click.option("--naming-dir", default="naming", show_default=True,
                     help="Pasta dos arquivos <tabela>.json de nomenclatura revisável")(f)
    f = click.option("--llm-model", default=None,
                     help=f"Modelo LangChain 'provedor:modelo' (ex: litellm:claude-sonnet-5-5, openai:gpt-4o-mini). "
                          f"Default: ${DEFAULT_MODEL_ENV} ou o LiteLLM do ~/.claude/settings.json (ANTHROPIC_MODEL). "
                          f"Vazio = heurística")(f)
    f = click.option("--source-db", envvar="DL_SOURCE_DB", default=None,
                     type=click.Choice(sorted(SOURCES), case_sensitive=False),
                     help="Banco de origem: define a tipagem e o conector do orquestrador. "
                          "Default: servers[].type do contrato, $DL_SOURCE_DB ou postgres")(f)
    f = click.option("--language", envvar="DL_LANGUAGE", default=None,
                     type=click.Choice(["pyspark", "scala"], case_sensitive=False),
                     help="Linguagem do projeto de transformação. "
                          "Default: transformationLanguage do contrato, $DL_LANGUAGE ou pyspark")(f)
    f = click.option("--codecommit-transformation", default="",
                     help="Repositório CodeCommit do pipeline da transformação. Default: <dataset>-transformation")(f)
    f = click.option("--github-org", default="datalake-org", show_default=True,
                     help="Organização GitHub usada no remote origin e no catalog-info.yaml")(f)
    f = click.option("--merge-keys", default="",
                     help="Colunas da chave de merge do Delta na transformação, separadas por vírgula. "
                          "Ex: actor_id ou cd_credenciadora,nm_produto,data. Vazio = PK do DDL")(f)
    f = click.option("--partition-col", default="",
                     help="Coluna de data/timestamp da origem usada no filtro incremental, na leitura JDBC paralela "
                          "e na partição da transformação. Ex: DH_INCL_RGST. Vazio = inferida (created_at/updated_at)")(f)
    f = click.option("--encrypt", "encrypt", default="",
                     help="Colunas (nome do DDL) criptografadas na ingestão, separadas por vírgula. Ex: nu_cpf,nu_cnpj")(f)
    f = click.option("--table", "contract_table", default="",
                     help="Tabela do data contract (schema[].name). Obrigatória se o contrato tiver mais de uma")(f)
    f = click.option("--contract", "contract_path", required=False, type=click.Path(exists=True),
                     help="Data contract ODCS (.odcs.yaml). Substitui o --ddl e preenche dataset, banco, partição, "
                          "merge e criptografia (flags informadas prevalecem)")(f)
    f = click.option("--ddl", "--schema", "ddl", required=False, type=click.Path(exists=True, dir_okay=False),
                     help="DDL (.sql) ou qualquer arquivo com nome e tipo dos campos: query SELECT, Avro/JSON Schema/StructType (.json), lista de campos (.csv, .xlsx, .md) ou dados (.parquet, .csv)")(f)
    f = click.option("--tipagem", "tipagem_path", envvar="DL_TIPAGEM", required=False, type=click.Path(exists=True),
                     help="Planilha Tipagem.xlsx (Tipo Origem → Tipo Final). Default: $DL_TIPAGEM; sem ela vale a tabela oficial embutida")(f)
    return f


def _read_fields(path: str) -> str:
    """Arquivo de entrada (DDL, query, JSON, planilha, parquet...) → DDL."""
    try:
        return read_schema(Path(path))
    except (ValueError, UnicodeDecodeError) as e:
        raise click.UsageError(f"{path}: {e}") from None


def _initial_state(ddl: str | None, sample_path: str | None, dataset: str | None, tipagem_path: str | None,
                   llm_model: str | None, naming_dir: str, dry_run: bool, encrypt: str = "",
                   source_db: str | None = None, partition_col: str = "", merge_keys: str = "",
                   github_org: str = "datalake-org", codecommit_transformation: str = "",
                   contract_path: str | None = None, contract_table: str = "",
                   contract_text: str = "", language: str | None = None) -> FrameworkState:
    if contract_path:
        contract_text = Path(contract_path).read_text(encoding="utf-8")
    if bool(ddl) == bool(contract_text):
        raise click.UsageError("Informe --ddl ou --contract (um dos dois)")

    encrypt_columns = [c.strip() for c in encrypt.split(",") if c.strip()]
    merge_key_list = [c.strip() for c in merge_keys.split(",") if c.strip()]

    # Data contract: preenche o que não veio por flag
    if contract_text:
        ct = resolve_table(load_contract(contract_text), contract_table)
        extra = custom_props(ct.contract)
        dataset = dataset or ct.dataset
        source_db = source_db or ct.source_db
        partition_col = partition_col or ct.partition_col
        merge_key_list = merge_key_list or ct.merge_keys
        encrypt_columns = list(dict.fromkeys(encrypt_columns + ct.encrypt_columns))
        if github_org == "datalake-org" and extra.get("githubOrg"):
            github_org = extra["githubOrg"]
        codecommit_transformation = codecommit_transformation or extra.get("codecommitTransformation", "")
        language = language or extra.get("transformationLanguage")
        contract_table = ct.table["name"]

    if not dataset:
        raise click.UsageError("Informe --dataset (com --ddl ele é obrigatório; no contrato vem de dataProduct)")
    source_db = (source_db or "postgres").lower()
    try:
        language = resolve_language(language)
    except ValueError as e:
        raise click.UsageError(str(e)) from None

    return {
        "ddl": _read_fields(ddl) if ddl else "",
        "contract": contract_text,
        "contract_table": contract_table,
        "sample_path": sample_path or "",
        "dataset": dataset,
        "project_name": dataset,
        "tipagem_path": tipagem_path or "",
        "llm_model": resolve_model_name(llm_model),
        "naming_dir": naming_dir,
        "dry_run": dry_run,
        "output_dir": ".",
        "encrypt_columns": encrypt_columns,
        "source_db": source_db,
        "partition_col": partition_col,
        "merge_keys": merge_key_list,
        "github_org": github_org,
        "codecommit_transformation": codecommit_transformation,
        "language": language,
        "schema": None,
        "profile": None,
        "naming_source": "",
        "naming_warnings": [],
        "input_files": {},
        "transform_files": {},
        "input_project_dir": "",
        "transform_project_dir": "",
        "compile_errors": [],
        "input_compiled": False,
        "transform_compiled": False,
        "iterations": 0,
        "max_iterations": 5,
        "skip_input": False,
        "status": "profiling",
        "error_message": "",
    }


@main.command()
@click.option("--sample", "sample_path", required=False, type=click.Path(exists=True), help="Amostra (.csv, .json, .parquet) — ajuda o LLM com exemplos de valores")
@click.option("--dataset", default=None, help="Nome do dataset (ex: vendas). Default: dataProduct do contrato (obrigatório com --ddl)")
@click.option("--output", "-o", required=False, type=click.Path(), help="Grava o bloco de campos neste arquivo")
@click.option("--dry-run", is_flag=True, help="Não grava o arquivo de nomenclatura")
@naming_options
def campos(sample_path: str | None, dataset: str | None, output: str | None, dry_run: bool,
           ddl: str | None, contract_path: str | None, contract_table: str,
           tipagem_path: str | None, llm_model: str | None, naming_dir: str, encrypt: str,
           source_db: str | None, partition_col: str,
           merge_keys: str, github_org: str, codecommit_transformation: str, language: str | None):
    """Gera só o bloco de campos (FieldSpec em PySpark ou ModelField em Scala) a partir do DDL."""
    from framework.agents.naming import naming_agent
    from framework.agents.profiler import profiler_agent
    from framework.agents.transform_gen import render_field_block

    state = _initial_state(ddl, sample_path, dataset, tipagem_path, llm_model, naming_dir, dry_run, encrypt,
                           source_db, partition_col, merge_keys,
                           github_org, codecommit_transformation,
                           contract_path, contract_table, language=language)
    state = {**state, **profiler_agent(state)}
    state = {**state, **naming_agent(state)}

    block = render_field_block(state["schema"], state.get("profile"), state["language"])
    if output:
        Path(output).write_text(block + "\n", encoding="utf-8")
        console.print(f"[green]Bloco gravado em {output}[/green]")
    click.echo()
    click.echo(block)


def _contract_targets(contract_path: str) -> list[tuple[str, str]]:
    """Contrato (todas as tabelas) ou pasta de contratos (*.odcs.yaml) → [(arquivo, tabela)], com as FKs cruzadas."""
    p = Path(contract_path)
    files = sorted(p.rglob("*.odcs.yaml")) if p.is_dir() else [p]
    if not files:
        raise click.UsageError(f"Nenhum *.odcs.yaml em {contract_path}")
    try:
        contracts = [(f, load_contract(f.read_text(encoding="utf-8"))) for f in files]
        check_relationships([c for _, c in contracts])
    except ValueError as e:
        raise click.UsageError(str(e)) from None
    return [(str(f), t["name"]) for f, c in contracts for t in c["schema"]]


@main.command()
@click.option("--ddl", "--schema", "ddl", required=True, type=click.Path(exists=True, dir_okay=False),
              help="DDL com um ou vários CREATE TABLE, ou outro arquivo com nome e tipo dos campos (veja generate --help)")
@click.option("--dataset", required=True, help="Nome do dataset (dataProduct do contrato)")
@click.option("--source-db", default="postgres", show_default=True,
              type=click.Choice(sorted(SOURCES), case_sensitive=False), help="Banco de origem")
@click.option("--raw-partition-column", default="", help="Coluna de partição da raw (ex: dt_ingestao)")
@click.option("--env", "environment", default="prd", show_default=True, help="Ambiente do servidor de origem")
@click.option("--host", default="", help="Host do banco de origem")
@click.option("--port", default=None, type=int, help="Porta do banco de origem")
@click.option("--database", default="", help="Database (ou serviceName no Oracle)")
@click.option("--secret-id", default="", help="ARN da secret com usuário/senha")
@click.option("--language", default="pyspark", show_default=True,
              type=click.Choice(["pyspark", "scala"], case_sensitive=False), help="Linguagem da transformação")
@click.option("--output-dir", "-o", default="contracts", show_default=True, type=click.Path(file_okay=False),
              help="Pasta dos contratos: grava <pasta>/<dataset>/<tabela>.odcs.yaml")
def contrato(ddl: str, dataset: str, source_db: str, raw_partition_column: str, environment: str, host: str,
             port: int | None, database: str, secret_id: str, language: str, output_dir: str):
    """Cria um data contract (ODCS) por tabela da DDL, com as chaves estrangeiras em relationships."""
    from framework.ui import service

    form = {"dataset": dataset, "sourceType": source_db.lower(), "rawPartitionColumn": raw_partition_column,
            "transformationLanguage": language.lower()}
    servers = [{"environment": environment, "host": host, "port": port, "database": database, "secretId": secret_id}]
    try:
        contracts = service.contracts_from_ddl(_read_fields(ddl), form, servers)
    except ValueError as e:
        raise click.ClickException(str(e)) from None

    folder = Path(output_dir) / dataset.lower()
    folder.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]{len(contracts)} contrato(s) em {folder.resolve()}[/green]")
    for contract in contracts:
        table = contract["schema"][0]
        path = folder / f"{table['name']}.odcs.yaml"
        path.write_text(service.dump_contract(contract), encoding="utf-8")
        refs = [f"{p['name']} → {r['to']}" for p in table["properties"] for r in p.get("relationships") or []]
        console.print(f"  {path.name}: {len(table['properties'])} colunas"
                      + (f"; relações: {', '.join(refs)}" if refs else ""))
    console.print(f"\nGere tudo com: dl-gen generate --contract {folder}")


@main.command()
@click.option("--sample", "sample_path", required=False, type=click.Path(exists=True), help="Caminho da amostra (.csv, .json, .parquet)")
@click.option("--dataset", default=None, help="Nome do dataset (ex: vendas). Default: dataProduct do contrato (obrigatório com --ddl)")
@click.option("--publish-s3", default="", help="Envia o ingestion.yml para este prefixo S3 (ex: s3://bucket/ingestion-config/). Exige boto3")
@click.option("--max-iterations", default=5, help="Máximo de iterações do feedback loop")
@click.option("--skip-input", is_flag=True, help="Pula a geração do ingestion.yml (só Transformation)")
@click.option("--append", is_flag=True, help="Acumula no projeto de transformação já existente em --output-dir")
@click.option("--all-tables", is_flag=True,
              help="Gera todas as tabelas do contrato (um ingestion.yml por tabela, um projeto de transformação). "
                   "Com --contract <pasta> é automático")
@click.option("--dry-run", is_flag=True, help="Não escreve arquivos no disco, só mostra")
@click.option("--output-dir", default=".", show_default=True, type=click.Path(file_okay=False),
              help="Pasta onde os projetos são criados (default: pasta atual)")
@naming_options
@click.pass_context
def generate(ctx: click.Context, sample_path: str | None, dataset: str | None, publish_s3: str,
             max_iterations: int, skip_input: bool, append: bool, all_tables: bool, dry_run: bool, output_dir: str,
             ddl: str | None, contract_path: str | None, contract_table: str,
             tipagem_path: str | None, llm_model: str | None, naming_dir: str, encrypt: str,
             source_db: str | None, partition_col: str,
             merge_keys: str, github_org: str, codecommit_transformation: str, language: str | None):
    """Gera o ingestion.yml e o projeto de transformação a partir do data contract ou do DDL."""
    if all_tables or (contract_path and Path(contract_path).is_dir()):
        if not contract_path:
            raise click.UsageError("--all-tables exige --contract")
        targets = _contract_targets(contract_path)
        for i, (path, table) in enumerate(targets):
            console.print(f"\n[bold cyan]── Tabela {i + 1}/{len(targets)}: {table} ({Path(path).name})[/bold cyan]")
            # A partir da segunda, acumula no mesmo projeto de transformação
            ctx.invoke(generate, **{**ctx.params, "all_tables": False, "contract_path": path,
                                    "contract_table": table, "append": append or i > 0})
        return

    # Estado inicial
    initial_state = _initial_state(ddl, sample_path, dataset, tipagem_path, llm_model, naming_dir, dry_run, encrypt,
                                   source_db, partition_col, merge_keys,
                                   github_org, codecommit_transformation,
                                   contract_path, contract_table, language=language)
    dataset = initial_state["dataset"]
    initial_state["max_iterations"] = max_iterations
    initial_state["skip_input"] = skip_input
    output_path = Path(output_dir).resolve()
    initial_state["output_dir"] = str(output_path)

    # --append: carrega arquivos já existentes do projeto de transformação
    if append:
        base_dir = output_path
        transform_dir = base_dir / f"{dataset}-transformation"
        if transform_dir.exists():
            existing_files = {}
            pattern = "*.scala" if initial_state["language"] == "scala" else "*.py"
            for f in transform_dir.rglob(pattern):
                rel = f.relative_to(base_dir).as_posix()
                existing_files[rel] = f.read_text(encoding="utf-8")
            initial_state["transform_files"] = existing_files
            initial_state["transform_project_dir"] = f"{dataset}-transformation"
            console.print(f"[yellow]--append: {len(existing_files)} arquivos carregados de {transform_dir}[/yellow]")
        else:
            console.print(f"[yellow]--append: projeto {transform_dir} não encontrado, começando do zero[/yellow]")

    # Banner
    console.print(Panel.fit(
        f"[bold]Data Lake Generator (dl-gen)[/bold]\n"
        f"{'Data contract: ' + contract_path if contract_path else 'DDL: ' + str(ddl)}\n"
        f"Amostra: {sample_path or '(nenhuma)'}\n"
        f"Dataset: {dataset}\n"
        f"Transformação: {initial_state['language']}\n"
        f"Destino: {output_path}\n"
        f"Max iterações: {max_iterations}\n"
        f"Skip Input: {skip_input}\n"
        f"Tipagem: {tipagem_path or '(padrão)'}\n"
        f"LLM nomenclatura: {initial_state['llm_model'] or '(heurística)'}\n"
        f"Criptografia: {', '.join(initial_state['encrypt_columns']) or '(nenhuma)'}\n"
        f"Banco de origem: {initial_state['source_db']}\n"
        f"Coluna de partição: {initial_state['partition_col'] or '(inferida)'}\n"
        f"Chave de merge: {', '.join(initial_state['merge_keys']) or '(PK do DDL)'}",
        title="🚀 Iniciando",
        border_style="cyan",
    ))

    # Constrói e executa o grafo
    app = build_graph()

    try:
        final_state = app.invoke(initial_state)

        # Resultado
        console.print()
        skipped = final_state.get("validation_skipped", "")
        if skipped:
            console.print(Panel.fit(
                f"[bold green]✅ Projetos gerados[/bold green] [yellow](não compilados: {skipped})[/yellow]\n\n"
                f"Ingestão: {output_path / final_state.get('input_project_dir', '')}"
                " (ingestion.yml)\n"
                f"Transformação: {output_path / final_state.get('transform_project_dir', '')}",
                title="Gerado",
                border_style="green",
            ))
        elif final_state.get("input_compiled") and final_state.get("transform_compiled"):
            console.print(Panel.fit(
                f"[bold green]✅ Projetos gerados e compilados com sucesso![/bold green]\n\n"
                f"Ingestão: {final_state.get('input_project_dir', '')}\n"
                f"Transformação: {final_state.get('transform_project_dir', '')}",
                title="Sucesso",
                border_style="green",
            ))
        elif final_state.get("status") == "error":
            console.print(Panel.fit(
                f"[bold red]❌ Falha após {final_state.get('iterations', 0)} iterações[/bold red]\n\n"
                f"{final_state.get('error_message', 'Erro desconhecido')}",
                title="Erro",
                border_style="red",
            ))
        else:
            input_ok = "✅" if final_state.get("input_compiled") else "❌"
            transform_ok = "✅" if final_state.get("transform_compiled") else "❌"
            console.print(Panel.fit(
                f"Ingestão: {input_ok}\n"
                f"Transformação: {transform_ok}\n"
                f"Iterações: {final_state.get('iterations', 0)}",
                title="Resultado",
                border_style="yellow",
            ))

        # Modo contrato: publica o ingestion.yml no S3 lido pelo orquestrador
        if publish_s3 and not dry_run:
            from framework.publish import publish_to_s3
            for rel_path, content in final_state.get("input_files", {}).items():
                console.print(f"[green]☁️  {publish_to_s3(publish_s3, rel_path, content)}[/green]")

        # Lista arquivos gerados
        if final_state.get("naming_warnings"):
            console.print(f"\n[yellow]Revise a nomenclatura em {Path(naming_dir).resolve()}[/yellow]")
        console.print("\n[bold]Arquivos (não gravados — dry-run):[/bold]" if dry_run else "\n[bold]Arquivos gerados:[/bold]")
        all_files = {**final_state.get("input_files", {}), **final_state.get("transform_files", {})}
        for path in sorted(all_files):
            console.print(f"  📄 {path}")

    except Exception as e:
        console.print(f"\n[bold red]Erro:[/bold red] {e}")
        sys.exit(1)


@main.command()
@click.option("--llm-model", default=None, envvar=DEFAULT_MODEL_ENV,
              help="Modelo a testar (ex: litellm:<modelo>). Default: $DL_LLM_MODEL ou ANTHROPIC_MODEL do settings.json")
def llm(llm_model: str | None):
    """Testa o LLM de verdade: confere a configuração e faz uma chamada curta (LiteLLM pela lib openai)."""
    from framework.llm import check_model, ping

    model = resolve_model_name(llm_model)
    level, message = check_model(model)
    console.print(f"Modelo: {model or '(nenhum)'}\nConfiguração: {message}")
    if level in ("off", "error"):
        sys.exit(1)
    try:
        console.print(f"[green]Resposta do LLM:[/green] {ping(model)}")
    except Exception as e:  # rede, chave recusada, modelo inexistente no proxy...
        console.print(f"[bold red]Falhou:[/bold red] {type(e).__name__}: {e}")
        sys.exit(1)


@main.command()
def skills():
    """Lista as skills do agente (pasta src/framework/skills): o que cada etapa sabe fazer."""
    from framework.skills import SKILLS_DIR, list_skills

    console.print(f"[cyan]Skills em {SKILLS_DIR}[/cyan]\n")
    for skill in list_skills():
        console.print(f"[bold]{skill.name}[/bold]  → {skill.used_by}\n  {skill.description}\n  {skill.path}\n")


@main.command()
@click.option("--port", default=8501, show_default=True, help="Porta da interface")
def ui(port: int):
    """Abre a interface (Data Contract Studio) no navegador: contrato → campos → validação → geração."""
    import subprocess

    try:
        import streamlit  # noqa: F401
    except ImportError:
        raise click.ClickException('A interface precisa do Streamlit: pip install -e ".[ui]"') from None
    app = Path(__file__).parent / "ui" / "app.py"
    console.print(f"[cyan]Abrindo a interface em http://localhost:{port} (Ctrl+C para sair)[/cyan]")
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port),
                              "--browser.gatherUsageStats", "false",
                              # tema do Studio (escuro)
                              "--theme.base", "dark", "--theme.primaryColor", "#6366f1", "--theme.baseRadius", "medium",
                              "--theme.showSidebarBorder", "true"]))


if __name__ == "__main__":
    main()

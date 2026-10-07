"""Agente 4 — Validator.

Compila (sem executar) os arquivos Python do projeto PySpark gerado e grava tudo em disco.
Não usa LLM nem depende do Spark instalado — é puramente determinístico.
"""

from __future__ import annotations

from pathlib import Path

from framework.repo import DEFAULT_GITHUB_ORG, github_remote, init_git_repo
from framework.state import FrameworkState


def _write_files_to_disk(files: dict[str, str], base_dir: str = ".") -> Path:
    """Escreve os arquivos gerados no disco e retorna o diretório do projeto."""
    if not files:
        return Path(base_dir)

    # O primeiro path determina o diretório base
    first_path = next(iter(files))
    project_dir = Path(base_dir) / Path(first_path).parts[0]

    for rel_path, content in files.items():
        full_path = Path(base_dir) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    return project_dir


def _write_project(files: dict[str, str], base_dir: str, github_org: str) -> Path:
    """Grava o projeto e inicializa o repositório git (sem commit)."""
    project_dir = _write_files_to_disk(files, base_dir)
    print(f"  📁 Gravado em {project_dir.resolve()}")
    print(f"     {init_git_repo(project_dir, github_remote(project_dir.name, github_org))}")
    return project_dir


def _write_ingestion_config(files: dict[str, str], base_dir: str) -> None:
    """Grava o ingestion.yml (sem git nem compilação)."""
    _write_files_to_disk(files, base_dir)
    for rel_path in files:
        print(f"  📄 Gravado {(Path(base_dir) / rel_path).resolve()}")


def _compile_python(files: dict[str, str]) -> tuple[bool, list[dict]]:
    """Compila (sem executar) os .py gerados, em memória — pega erros de sintaxe dos templates.

    Returns:
        (success, errors) — errors é lista de {file, error, agent_origin}.
    """
    errors = []
    for rel_path, content in files.items():
        if not rel_path.endswith(".py"):
            continue
        try:
            compile(content, rel_path, "exec")
        except SyntaxError as e:
            errors.append({"file": rel_path, "error": f"linha {e.lineno}: {e.msg}", "agent_origin": "unknown"})
    return not errors, errors


def validator_agent(state: FrameworkState) -> FrameworkState:
    """Agente 4: valida o projeto PySpark gerado (compilação dos .py) e grava em disco."""
    print("[Agente 4 — Validator] Iniciando validação...")

    base_dir = state.get("output_dir") or "."
    github_org = state.get("github_org") or DEFAULT_GITHUB_ORG

    # Dry-run: não grava nem compila
    if state.get("dry_run"):
        print("  Dry-run: nada gravado em disco.")
        return {"compile_errors": [], "input_compiled": True, "transform_compiled": True,
                "validation_skipped": "dry-run", "status": "validating"}

    all_errors: list[dict] = []

    # ingestion.yml: só grava (não há o que compilar)
    input_compiled = True
    if state.get("input_files"):
        _write_ingestion_config(state["input_files"], base_dir)

    # Valida projeto de transformação
    transform_compiled = True
    if state.get("transform_files"):
        print("  Compilando projeto de transformação...")
        transform_compiled, transform_errors = _compile_python(state["transform_files"])
        transform_dir = _write_project(state["transform_files"], base_dir, github_org)

        for e in transform_errors:
            e["agent_origin"] = "transform_gen"
        all_errors.extend(transform_errors)

        if transform_compiled:
            print(f"  ✅ Transformação compilou ({transform_dir.name})")
        else:
            print(f"  ❌ Transformação falhou ({len(transform_errors)} erros)")

    print("[Agente 4 — Validator] Concluído.")

    return {
        **state,
        "compile_errors": all_errors,
        "input_compiled": input_compiled,
        "transform_compiled": transform_compiled,
        "validation_skipped": "",
        "status": "validating",
    }

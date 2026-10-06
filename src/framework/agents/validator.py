"""Agente 4 — Validator.

Compila os projetos Scala gerados com sbt compile.
Não usa LLM — é puramente determinístico (subprocess + sbt).
"""

from __future__ import annotations

import shutil
import subprocess
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


def _run_sbt_compile(project_dir: Path) -> tuple[bool, list[dict]]:
    """Roda sbt compile no diretório do projeto.

    Returns:
        (success, errors) — errors é lista de {file, error, agent_origin}.
    """
    if not project_dir.exists():
        return False, [{"file": str(project_dir), "error": "Diretório não existe", "agent_origin": "unknown"}]

    try:
        result = subprocess.run(
            ["sbt", "compile"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max
        )

        if result.returncode == 0:
            return True, []

        # Extrai erros do output
        errors = []
        current_file = "unknown"
        for line in (result.stdout + result.stderr).splitlines():
            # sbt mostra erros no formato: [error] /path/to/file.scala:line: error message
            if "[error]" in line and ".scala" in line:
                parts = line.split()
                for p in parts:
                    if ".scala" in p:
                        current_file = p.split(":")[0]
                        break
                errors.append({
                    "file": current_file,
                    "error": line.strip(),
                    "agent_origin": "unknown",
                })

        if not errors:
            errors.append({
                "file": "unknown",
                "error": result.stderr[:500] if result.stderr else result.stdout[:500],
                "agent_origin": "unknown",
            })

        return False, errors

    except subprocess.TimeoutExpired:
        return False, [{"file": "unknown", "error": "sbt compile timeout (5min)", "agent_origin": "unknown"}]
    except FileNotFoundError:
        return False, [{"file": "unknown", "error": "sbt não encontrado no PATH", "agent_origin": "unknown"}]


def validator_agent(state: FrameworkState) -> FrameworkState:
    """Agente 4: valida os projetos Scala gerados com sbt compile."""
    print("[Agente 4 — Validator] Iniciando validação...")

    base_dir = state.get("output_dir") or "."
    github_org = state.get("github_org") or DEFAULT_GITHUB_ORG

    # Dry-run: não grava nem compila
    if state.get("dry_run"):
        print("  Dry-run: nada gravado em disco.")
        return {"compile_errors": [], "input_compiled": True, "transform_compiled": True,
                "validation_skipped": "dry-run", "status": "validating"}

    # Sem sbt: grava os projetos, mas não compila (evita o loop do Fixer sem motivo)
    if shutil.which("sbt") is None:
        if state.get("input_files"):
            _write_ingestion_config(state["input_files"], base_dir)
        if state.get("transform_files"):
            _write_project(state["transform_files"], base_dir, github_org)
        print("  ⚠️ sbt não encontrado no PATH — projetos gravados sem compilar.")
        return {"compile_errors": [], "input_compiled": True, "transform_compiled": True,
                "validation_skipped": "sbt não encontrado no PATH", "status": "validating"}

    all_errors: list[dict] = []

    # ingestion.yml: só grava (não há o que compilar)
    input_compiled = True
    if state.get("input_files"):
        _write_ingestion_config(state["input_files"], base_dir)

    # Valida projeto de transformação
    transform_compiled = True
    if state.get("transform_files"):
        print("  Compilando projeto de transformação...")
        transform_dir = _write_project(state["transform_files"], base_dir, github_org)
        transform_compiled, transform_errors = _run_sbt_compile(transform_dir)

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

"""Arquivos de repositório comuns aos projetos gerados (modelo do projeto de referência).

Gera .github/workflows/pipeline.yml (espelho GitHub → CodeCommit), catalog-info.yaml
(Backstage) e .gitignore, e inicializa o repositório git com o remote do GitHub.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

DEFAULT_GITHUB_ORG = "datalake-org"
TEMPLATES_DIR = Path(__file__).parent / "templates" / "repo"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def repo_files(project_name: str, codecommit_repo: str, github_org: str = DEFAULT_GITHUB_ORG) -> dict[str, str]:
    """Arquivos de repositório do projeto, com caminho relativo ao diretório pai."""
    env = _env()
    # Pipeline é texto puro (usa ${{ }} do GitHub Actions) — só troca o repositório CodeCommit
    pipeline = (TEMPLATES_DIR / "pipeline.yml.tpl").read_text(encoding="utf-8")
    return {
        f"{project_name}/.github/workflows/pipeline.yml": pipeline.replace("__CODECOMMIT_REPO__", codecommit_repo),
        f"{project_name}/catalog-info.yaml": env.get_template("catalog-info.yaml.j2").render(
            project_name=project_name, github_org=github_org),
        f"{project_name}/.gitignore": env.get_template("gitignore.j2").render(),
    }


def github_remote(project_name: str, github_org: str = DEFAULT_GITHUB_ORG) -> str:
    return f"https://github.com/{github_org}/{project_name}.git"


def init_git_repo(project_dir: Path, remote_url: str) -> str:
    """git init -b main + remote origin. Não faz commit nem push. Retorna o que foi feito."""
    if (project_dir / ".git").exists():
        return "repositório git já existia (mantido)"
    try:
        subprocess.run(["git", "init", "-b", "main"], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=project_dir, check=True,
                       capture_output=True, text=True)
        return f"git init (main) + origin {remote_url}"
    except FileNotFoundError:
        return "git não encontrado no PATH — repositório não inicializado"
    except subprocess.CalledProcessError as e:
        return f"falha no git: {(e.stderr or e.stdout).strip()}"

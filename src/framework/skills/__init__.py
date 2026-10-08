"""Skills do agente — o conhecimento que cada etapa aplica, em Markdown, fora do código.

Cada skill é uma pasta com um SKILL.md (frontmatter com name/description/agent + corpo) e, se precisar, uma pasta
references/ com os documentos de apoio. O índice está em README.md, nesta pasta.

As seções "## ..." do corpo podem ser lidas pelo código: a skill de nomenclatura guarda ali os prompts do LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).parent

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    agent: str
    path: Path
    body: str
    sections: dict[str, str] = field(default_factory=dict)

    def section(self, title: str) -> str:
        try:
            return self.sections[title]
        except KeyError:
            raise KeyError(f"Skill {self.name}: seção '## {title}' não encontrada em {self.path}") from None

    def reference(self, filename: str) -> Path:
        return self.path.parent / "references" / filename


def _sections(body: str) -> dict[str, str]:
    """'## Título' → texto até o próximo '## ' (sem as linhas em branco das pontas)."""
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.MULTILINE)
    return {title.strip(): text.strip("\n") for title, text in zip(parts[1::2], parts[2::2])}


def _parse(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: SKILL.md sem frontmatter (--- name/description ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    return Skill(name=str(meta.get("name") or path.parent.name), description=str(meta.get("description", "")).strip(),
                 agent=str(meta.get("agent", "")), path=path, body=body, sections=_sections(body))


@lru_cache(maxsize=None)
def load_skill(name: str) -> Skill:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill '{name}' não existe ({path})")
    return _parse(path)


def list_skills() -> list[Skill]:
    return [_parse(p) for p in sorted(SKILLS_DIR.glob("*/SKILL.md"))]

"""Skills do agente — o conhecimento que cada etapa aplica, em Markdown, fora do código.

Cada skill é uma pasta com um SKILL.md (frontmatter name/description + corpo) e, quando útil, scripts/ (código que
os templates espelham 1:1) e references/ (documentos de apoio). O índice está em README.md, nesta pasta.

As seções "## ..." do corpo podem ser lidas pelo código: a skill data-governance-names guarda ali o prompt do LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

SKILLS_DIR = Path(__file__).parent

# Onde cada skill é aplicada no dl-gen (as skills ficam como vieram, sem campo extra no frontmatter)
USED_BY: dict[str, str] = {
    "leitura-de-schema": "parsers/schema_reader.py",
    "data-governance-names": "agents/naming.py (prompt do LLM) e standards/nomenclatura.py",
    "ingestao": "agents/input_gen.py e ingestion_config.py",
    "sdd-specification": "templates/transformation/sdd_doc.md.j2",
    "project-structure": "agents/transform_gen.py e templates/transformation/*/static/utils",
    "processor-orchestration": "templates/transformation/*/processor",
    "job-parameters": "templates/transformation/*/main e utils/args_parser",
    "data-transformation-patterns": "agents/transform_gen.py (transformação padrão por tipo)",
    "catalyst-optimization": "static/utils/transform_column",
    "timestamp-handling": "static/utils/normalize_timestamp",
    "processing-timestamp": "templates/transformation/*/processor (run timestamp)",
    "enrichment-joins": "static/utils/apply_enrichment",
    "nested-field-extraction": "static/utils/nested_field_spec",
    "dataframe-persist-strategy": "templates/transformation/*/processor (persist)",
    "delta-write-patterns": "static/utils/delta_write_pattern",
    "hive-table-management": "static/utils/hive_table_manager",
    "error-handler": "static/error/spark_error_handler",
    "fact-to-fact-joins": "referência (o dl-gen ainda não gera joins fato-a-fato)",
}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    body: str
    sections: dict[str, str] = field(default_factory=dict)

    @property
    def used_by(self) -> str:
        return USED_BY.get(self.name, "")

    def section(self, title: str) -> str:
        try:
            return self.sections[title]
        except KeyError:
            raise KeyError(f"Skill {self.name}: seção '## {title}' não encontrada em {self.path}") from None

    def reference(self, filename: str) -> Path:
        return self.path.parent / "references" / filename


def _sections(body: str) -> dict[str, str]:
    """'## Título' → texto até o próximo '## ' fora de bloco de código (sem as linhas em branco das pontas)."""
    sections: dict[str, str] = {}
    title, lines, fenced = None, [], False
    for line in body.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^## +(.+?)\s*$", line)
        if m:
            if title is not None:
                sections[title] = "\n".join(lines).strip("\n")
            title, lines = m.group(1).strip(), []
        elif title is not None:
            lines.append(line)
    if title is not None:
        sections[title] = "\n".join(lines).strip("\n")
    return sections


def _parse(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: SKILL.md sem frontmatter (--- name/description ---)")
    meta = yaml.safe_load(m.group(1)) or {}
    body = text[m.end():]
    return Skill(name=str(meta.get("name") or path.parent.name), description=str(meta.get("description", "")).strip(),
                 path=path, body=body, sections=_sections(body))


@lru_cache(maxsize=None)
def load_skill(name: str) -> Skill:
    path = SKILLS_DIR / name / "SKILL.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill '{name}' não existe ({path})")
    return _parse(path)


def list_skills() -> list[Skill]:
    return [_parse(p) for p in sorted(SKILLS_DIR.glob("*/SKILL.md"))]

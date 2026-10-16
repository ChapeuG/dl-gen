"""Skills do agente: pasta src/framework/skills, um SKILL.md por skill."""

from __future__ import annotations

import re

from framework.agents.naming import NAMING_PROMPT
from framework.skills import SKILLS_DIR, USED_BY, list_skills, load_skill

TEMPLATES = SKILLS_DIR.parent / "templates" / "transformation" / "scala" / "static"


def test_every_skill_has_frontmatter_usage_and_index():
    skills = list_skills()
    index = (SKILLS_DIR / "README.md").read_text(encoding="utf-8")
    assert {s.name for s in skills} == set(USED_BY)
    for s in skills:
        assert s.name == s.path.parent.name and s.description, s.name
        assert f"]({s.name}/SKILL.md)" in index, s.name


def test_no_company_references():
    forbidden = re.compile(r"\belo\b|autoriza|bandeira|cielo|liquida", re.IGNORECASE)
    for f in SKILLS_DIR.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".scala", ".csv", ".txt"):
            assert not forbidden.search(f.read_text(encoding="utf-8")), f


def test_naming_prompt_comes_from_governance_skill():
    skill = load_skill("data-governance-names")
    assert skill.reference("padrao_nomenclatura.txt").exists()
    assert set(NAMING_PROMPT.input_variables) == {"reservados", "naturezas", "regras", "padroes", "source_table",
                                                  "dataset", "table_comment", "campos", "ja_definidos", "erros"}
    assert skill.section("Prompt do sistema").startswith("Você é especialista")
    assert "Use `dh` for date and time values." in skill.section("How to Decide the Prefix")
    assert "Do not confuse `id` and `cd`." in skill.section("Guardrails")


def _code_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def test_scala_templates_mirror_skill_scripts():
    """Os utilitários do projeto Scala gerado são os scripts das skills (o template só acrescenta casos [framework])."""
    mirrored = 0
    for script in SKILLS_DIR.glob("*/scripts/*.scala"):
        template = next(TEMPLATES.rglob(script.name), None)
        if template is None:
            continue
        expected, actual = _code_lines(script.read_text(encoding="utf-8")), iter(_code_lines(
            template.read_text(encoding="utf-8")))
        assert all(line in actual for line in expected), f"{template.name} divergiu de {script}"
        mirrored += 1
    assert mirrored >= 12

"""Skills do agente: pasta src/framework/skills, um SKILL.md por skill."""

from __future__ import annotations

from framework.agents.naming import NAMING_PROMPT
from framework.skills import SKILLS_DIR, list_skills, load_skill


def test_every_skill_has_frontmatter_and_is_indexed():
    skills = list_skills()
    index = (SKILLS_DIR / "README.md").read_text(encoding="utf-8")
    assert {s.name for s in skills} >= {"nomenclatura", "leitura-de-schema", "ingestao", "transformacao", "sdd"}
    for s in skills:
        assert s.description and s.agent, s.name
        assert f"]({s.path.parent.name}/SKILL.md)" in index, s.name


def test_naming_prompt_comes_from_skill():
    skill = load_skill("nomenclatura")
    assert skill.reference("padrao_nomenclatura.txt").exists()
    assert set(NAMING_PROMPT.input_variables) == {"reservados", "naturezas", "padroes", "source_table", "dataset",
                                                  "table_comment", "campos", "ja_definidos", "erros"}
    system = skill.section("Prompt do sistema")
    assert system.startswith("Você é especialista") and "## " not in system

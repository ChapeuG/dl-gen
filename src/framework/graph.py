"""Grafo LangGraph — orquestra os 5 agentes.

Fluxo:
    Profiler → Nomenclatura (subgrafo de nomenclatura) → (Input Gen ∥ Transform Gen) → Validator → Fixer → (volta ou done)
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from framework.state import FrameworkState
from framework.agents.profiler import profiler_agent
from framework.agents.naming import naming_agent
from framework.agents.input_gen import input_gen_agent
from framework.agents.transform_gen import transform_gen_agent
from framework.agents.validator import validator_agent
from framework.agents.fixer import fixer_agent


def _route_after_validation(state: FrameworkState) -> str:
    """Decide: vai pro fixer ou termina."""
    input_ok = state.get("input_compiled", True)
    transform_ok = state.get("transform_compiled", True)

    if input_ok and transform_ok:
        return "done"
    return "fix"


def _route_after_fix(state: FrameworkState) -> str:
    """Decide: qual agente re-chamar, ou desistir."""
    iterations = state.get("iterations", 0)
    max_iterations = state.get("max_iterations", 5)

    if iterations >= max_iterations:
        return "max_reached"

    # Decide qual gerador re-chamar baseado nos erros
    errors = state.get("compile_errors", [])
    has_input_errors = any(e["agent_origin"] == "input_gen" for e in errors)
    has_transform_errors = any(e["agent_origin"] == "transform_gen" for e in errors)

    # Prioriza transform (mais complexo)
    if has_transform_errors:
        return "transform"
    if has_input_errors:
        return "input"
    return "input"  # default


def build_graph():
    """Constrói e compila o grafo LangGraph."""
    graph = StateGraph(FrameworkState)

    # Nós = agentes
    graph.add_node("profiler", profiler_agent)
    graph.add_node("naming", naming_agent)
    graph.add_node("input_gen", input_gen_agent)
    graph.add_node("transform_gen", transform_gen_agent)
    graph.add_node("validator", validator_agent)
    graph.add_node("fixer", fixer_agent)

    # START → Profiler
    graph.add_edge(START, "profiler")

    # Profiler → Nomenclatura → ambos geradores (paralelo)
    graph.add_edge("profiler", "naming")
    graph.add_edge("naming", "input_gen")
    graph.add_edge("naming", "transform_gen")

    # Ambos → validator (barreira de sincronização)
    graph.add_edge("input_gen", "validator")
    graph.add_edge("transform_gen", "validator")

    # Validator decide: fix ou done
    graph.add_conditional_edges("validator", _route_after_validation, {
        "fix": "fixer",
        "done": END,
    })

    # Fixer decide: qual agente re-chamar
    graph.add_conditional_edges("fixer", _route_after_fix, {
        "input": "input_gen",
        "transform": "transform_gen",
        "max_reached": END,
    })

    return graph.compile()

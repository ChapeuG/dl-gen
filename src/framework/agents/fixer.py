"""Agente 5 — Fixer.

Recebe erros de compilação e decide qual agente re-chamar.
Nesta versão inicial, apenas loga os erros — a correção automática
via LLM seria implementada na Fase 3.
"""

from __future__ import annotations

from framework.state import FrameworkState


def fixer_agent(state: FrameworkState) -> FrameworkState:
    """Agente 5: analisa erros e prepara re-geração.

    Por enquanto, apenas reporta os erros. A integração com LLM
    para re-gerar arquivos específicos viria na Fase 3.
    """
    print("[Agente 5 — Fixer] Analisando erros...")

    errors = state.get("compile_errors", [])
    iterations = state.get("iterations", 0) + 1
    max_iterations = state.get("max_iterations", 5)

    for err in errors:
        print(f"  ❌ {err['file']}: {err['error'][:100]}")

    if iterations >= max_iterations:
        print(f"  ⚠️ Teto de {max_iterations} iterações atingido. Parando.")
        return {
            **state,
            "iterations": iterations,
            "status": "error",
            "error_message": f"Compilação falhou após {max_iterations} iterações",
        }

    print(f"  Iteração {iterations}/{max_iterations}. Re-gerando...")

    return {
        **state,
        "iterations": iterations,
        "status": "fixing",
    }

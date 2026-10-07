"""Data Contract Studio — interface do framework (dl-gen ui).

Etapas (menu lateral): 1. Contrato → 2. Campos e nomenclatura → 3. Validação → 4. Geração.
Nas etapas 1 e 2 o painel da direita mostra o contrato ao vivo e a saúde do contrato; cada pendência
tem um "Corrigir" que leva ao campo. A lógica fica em framework.ui.service; aqui só a tela.
Os botões usam callbacks (on_click): eles rodam antes da tela ser desenhada, então a navegação
não precisa de st.rerun().
"""

from __future__ import annotations

import io
import math
import zipfile

import pandas as pd
import streamlit as st

from framework.llm import check_model, resolve_model_name
from framework.ui import service

st.set_page_config(page_title="Data Contract Studio", page_icon=":material/contract:", layout="wide")

STEPS = [
    ("Contrato", "Tabela, origem e destino", ":material/table_edit:"),
    ("Campos", "Nomenclatura da transformação", ":material/view_column:"),
    ("Validação", "Conferência antes de gerar", ":material/verified:"),
    ("Geração", "Contrato, ingestion.yml e transformação", ":material/deployed_code:"),
]
ROLE_COLORS = ["#8b5cf6", "#0ea5e9", "#ef4444", "#94a3b8"]  # na ordem de service.ROLES
ROLES_HELP = ("PK: chave do MERGE. incremental: coluna de data do filtro (só uma). "
              "LGPD: criptografar. obrigatória: não aceita nulo.")
NAMING_FILTERS = ["Todas", "Renomeadas", "Editadas por você", "Sensíveis"]
# Pendência → etapa onde se corrige (o resto fica no formulário da etapa 1)
TARGET_STEP = {"naming": 1}

st.markdown("""
<style>
[data-testid="stSidebar"] .stButton button > div { justify-content: flex-start; width: 100%; }
.st-key-health .stButton button, .st-key-checks .stButton button { padding: 0; min-height: 0; text-align: left; }
.st-key-health .stButton button > div, .st-key-checks .stButton button > div { justify-content: flex-start; }
[data-testid="stMetricValue"] { font-size: 1.6rem; }
</style>
""", unsafe_allow_html=True)


# ── Estado ─────────────────────────────────────────────────────────────

ss = st.session_state
ss.setdefault("step", 0)
ss.setdefault("max_step", 0)        # etapa mais adiantada já aberta (libera o menu lateral)
ss.setdefault("form", service.empty_form())
ss.setdefault("servers", service.empty_servers())
ss.setdefault("columns", [])
ss.setdefault("naming", None)       # NamingResult
ss.setdefault("naming_rows", [])
ss.setdefault("proposals", {})      # coluna na origem → nome sugerido (heurística/LLM/contrato)
ss.setdefault("selected", set())    # linhas marcadas na tabela de campos
ss.setdefault("validation", None)   # ValidationResult
ss.setdefault("result", None)       # GenerationResult
ss.setdefault("flash", None)        # (nível, mensagem) mostrada uma vez
ss.setdefault("focus", None)        # pendência destacada pelo "Corrigir"
ss.setdefault("scroll", False)      # rola até o destaque uma vez
ss.setdefault("editor_version", 0)  # muda quando as tabelas editáveis precisam recarregar
# Base das tabelas editáveis: só muda ao trocar de etapa/importar (o editor guarda as edições sobre ela)
ss.setdefault("base", {"servers": ss.servers, "columns": ss.columns, "naming_rows": ss.naming_rows})
ss.setdefault("out_dir", "")  # vazio = service.default_output_dir()
ss.setdefault("llm_model", resolve_model_name(""))


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame do editor → lista de dicts sem NaN."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}
            for r in df.to_dict("records")]


def _as_list(value) -> list:
    return [] if value is None or (isinstance(value, float) and math.isnan(value)) else list(value)


def _go(step: int, reload_widgets: bool = False):
    """Troca de etapa (chamada dentro de callbacks). reload_widgets: os dados mudaram por fora (importação)."""
    ss.step = step
    ss.max_step = max(ss.max_step, step)
    ss.focus = None
    ss.base = {"servers": ss.servers, "columns": ss.columns, "naming_rows": ss.naming_rows}
    ss.editor_version += 1
    if reload_widgets:
        for k in [k for k in ss if str(k).startswith("in_")]:
            del ss[k]


def _flash(level: str, message: str):
    ss.flash = (level, message)


def current_contract(with_naming: bool = True) -> dict:
    naming = service.naming_map(ss.naming_rows) if with_naming and ss.naming_rows else None
    return service.build_contract(ss.form, ss.servers, ss.columns, naming)


# ── Ações (callbacks) ──────────────────────────────────────────────────

def cb_reset():
    for k in list(ss):
        del ss[k]


def cb_import_ddl():
    try:
        form, rows = service.columns_from_ddl(ss.get("ddl_text", ""), ss.form.get("sourceType", "postgres"))
    except ValueError as e:
        _flash("error", f"Não consegui ler a DDL: {e}")
        return
    ss.form.update({k: v for k, v in form.items() if v and not ss.form.get(k)})
    ss.columns, ss.naming_rows = rows, []
    _flash("success", f"{len(rows)} colunas importadas da DDL.")
    _go(0, reload_widgets=True)


def cb_load_contract():
    up = ss.get("upload")
    if up is None:
        return
    try:
        ss.form, ss.servers, ss.columns = service.form_from_contract(up.getvalue().decode("utf-8"))
    except ValueError as e:
        _flash("error", str(e))
        return
    ss.naming_rows = []
    _flash("success", "Contrato carregado.")
    _go(0, reload_widgets=True)


def _propose():
    ss.naming = service.propose_naming(service.dump_contract(current_contract(with_naming=False)), ss.llm_model)
    ss.naming_rows = ss.naming.rows
    ss.proposals = {r["raw_field"]: r["staging_field"] for r in ss.naming.rows}
    ss.selected = set()


def cb_to_fields():
    try:
        _propose()
    except Exception as e:  # noqa: BLE001 — mostra o motivo na tela
        _flash("error", f"Não consegui montar o contrato: {e}")
        return
    _go(1)


def cb_resuggest():
    for c in ss.columns:
        c.pop("stagingName", None)
    ss.naming_rows = []
    try:
        _propose()
    except Exception as e:  # noqa: BLE001
        _flash("error", str(e))
    _go(1)


def cb_rename_selected(use_origin: bool):
    """Nas linhas marcadas: volta para a sugestão ou usa o nome da coluna na origem."""
    if not ss.selected:
        _flash("info", "Marque as linhas na coluna da esquerda da tabela.")
        return
    for r in ss.naming_rows:
        if r["raw_field"] in ss.selected:
            r["staging_field"] = r["raw_field"].lower() if use_origin else ss.proposals.get(r["raw_field"], r["staging_field"])
    _flash("success", f"{len(ss.selected)} nome(s) {'iguais aos da origem' if use_origin else 'de volta à sugestão'}.")
    ss.selected = set()
    _go(1)


def cb_naming_filter(name: str):
    # O filtro troca as linhas da tabela: guarda o que já foi editado antes de recarregar
    ss.naming_filter = name
    ss.base["naming_rows"] = ss.naming_rows
    ss.editor_version += 1


def cb_validate():
    ss.validation = service.validate(current_contract())
    _go(2)


def cb_nav(step: int):
    if step == 1 and not ss.naming_rows:
        cb_to_fields()
    elif step == 2:
        cb_validate()
    else:
        _go(step)


def cb_fix(target: str):
    """'Corrigir' de uma pendência: vai para a etapa do campo e destaca o campo."""
    _go(TARGET_STEP.get(target, 0))
    ss.focus, ss.scroll = target, True


def cb_generate():
    prefix = ss.get("publish_prefix", "") if ss.get("publish") else ""
    try:
        ss.result = service.generate(current_contract(), ss.out_dir, ss.llm_model, prefix)
    except Exception as e:  # noqa: BLE001
        _flash("error", f"Falha na geração: {e}")


# ── Componentes ────────────────────────────────────────────────────────

def field_input(label: str, key: str, help: str | None = None, placeholder: str = ""):
    """Campo de texto ligado a ss.form[key] (recarrega do formulário quando a tela volta)."""
    wk = f"in_{key}"
    if wk not in ss:
        ss[wk] = str(ss.form.get(key) or "")
    st.text_input(label, help=help, placeholder=placeholder, key=wk)
    ss.form[key] = ss[wk]


def bound(widget, label: str, key: str, **kwargs):
    """Outros widgets ligados a ss.form[key]."""
    wk = f"in_{key}"
    if wk not in ss:
        ss[wk] = ss.form.get(key)
    widget(label, key=wk, **kwargs)
    ss.form[key] = ss[wk]


def _element_key(target: str) -> str:
    """Pendência → chave do elemento na tela (o Streamlit põe a classe st-key-<chave> no elemento)."""
    return f"sec_{target}" if target in ("columns", "servers", "naming") else f"in_{target}"


def highlight_focus(checks: list[service.Check]):
    """Contorna o campo da pendência escolhida enquanto ela não for resolvida."""
    if not ss.focus or not any(c.target == ss.focus and c.level != "ok" for c in checks):
        ss.focus = None
        return
    css = f".st-key-{_element_key(ss.focus)}"
    st.html(f"<style>{css} {{ outline: 2px solid #ef4444; outline-offset: 6px; border-radius: 8px; }}</style>")
    if ss.scroll:
        ss.scroll = False
        st.html(f"<script>setTimeout(() => document.querySelector('{css}')"
                "?.scrollIntoView({behavior: 'smooth', block: 'center'}), 400)</script>",
                unsafe_allow_javascript=True)


def checklist(checks: list[service.Check], key: str, detail: bool = True):
    """Lista de conferências; clicar numa pendência leva ao campo que a resolve."""
    icons = {"ok": ":material/check_circle:", "warning": ":material/warning:", "error": ":material/cancel:"}
    colors = {"ok": "green", "warning": "orange", "error": "red"}
    order = {"error": 0, "warning": 1, "ok": 2}
    with st.container(key=key, gap="small"):
        for i, c in sorted(enumerate(checks), key=lambda x: order[x[1].level]):
            if c.level != "ok" and c.target:
                st.button(f":{colors[c.level]}[{c.title}] →", key=f"fix_{key}_{i}",
                          type="tertiary", icon=icons[c.level], help=c.detail or None, on_click=cb_fix,
                          args=(c.target,))
            else:
                st.markdown(f":{colors[c.level]}[{icons[c.level]}] {c.title}")
            if detail and c.detail:
                st.caption(c.detail)


@st.dialog("Data contract", width="large")
def show_contract(text: str):
    st.code(text, language="yaml")


def preview_panel(contract_text: str, checks: list[service.Check]):
    with st.container(border=True):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown("**Preview ao vivo**", width="stretch")
        if head.button("Expandir", icon=":material/open_in_full:", type="tertiary"):
            show_contract(contract_text)
        st.code(contract_text, language="yaml", height=360)
    with st.container(border=True):
        errors = sum(c.level == "error" for c in checks)
        warnings = sum(c.level == "warning" for c in checks)
        summary = ", ".join(t for t in [f"{errors} pendência(s)" if errors else "",
                                         f"{warnings} aviso(s)" if warnings else ""] if t)
        st.markdown(f"**Saúde do contrato** · :gray[{summary}]" if summary else
                    "**Saúde do contrato** · :green[tudo certo]")
        checklist(checks, "health", detail=False)


LLM_ICONS = {"ok": ":material/check_circle:", "warning": ":material/help:", "error": ":material/link_off:"}


@st.cache_data(ttl=60, show_spinner=False)
def llm_status(model: str) -> tuple[str, str]:
    """Situação do LLM na barra lateral (cache: o apiKeyHelper do settings.json pode demorar)."""
    return check_model(model)


# ── Etapa 1: Contrato ──────────────────────────────────────────────────

def step_contract():
    with st.expander("Preencher a partir de uma DDL ou de um contrato existente", icon=":material/bolt:",
                     expanded=not ss.columns):
        tab_ddl, tab_contract = st.tabs(["Colar DDL (CREATE TABLE)", "Abrir data contract (.odcs.yaml)"])
        with tab_ddl:
            st.text_area("DDL", key="ddl_text", height=160, label_visibility="collapsed",
                         placeholder="CREATE TABLE public.cliente (\n  id INTEGER PRIMARY KEY,\n  ...\n);")
            st.button("Importar colunas da DDL", disabled=not ss.get("ddl_text", "").strip(), on_click=cb_import_ddl)
        with tab_contract:
            st.file_uploader("Data contract", type=["yaml", "yml"], key="upload", label_visibility="collapsed")
            st.button("Carregar contrato", disabled=ss.get("upload") is None, on_click=cb_load_contract)

    with st.container(border=True):
        st.markdown("##### :material/badge: Identificação")
        c1, c2, c3 = st.columns(3)
        with c1:
            field_input("Dataset *", "dataset", "Vira o dataProduct do contrato e o nome dos projetos.", "vendas")
        with c2:
            field_input("Tabela *", "table", "Nome da tabela na raw e na staging.", "cliente")
        with c3:
            field_input("Domínio", "domain", placeholder="cartoes")
        c1, c2 = st.columns([2, 1])
        with c1:
            field_input("Descrição da tabela", "description", placeholder="Cadastro de clientes...")
        with c2:
            field_input("Dono do dado (usuário)", "owner")

    with st.container(border=True):
        st.markdown("##### :material/database: Origem")
        c1, c2, c3 = st.columns(3)
        with c1:
            if ss.form.get("sourceType") not in service.SOURCE_TYPES:
                ss.form["sourceType"] = "postgres"
            bound(st.selectbox, "Banco de origem *", "sourceType", options=service.SOURCE_TYPES)
        oracle = ss.form["sourceType"] == "oracle"
        with c2:
            field_input("Tabela na origem", "physicalName", "schema.tabela. Vazio = nome da tabela.", "public.cliente")
        with c3:
            if not oracle:
                field_input("Schema", "schema", "Vazio = prefixo da tabela na origem (ou public/dbo).", "public")
        st.caption("Um servidor por ambiente. A secret guarda usuário e senha (nunca coloque senha aqui).")
        with st.container(key="sec_servers"):
            servers = st.data_editor(
                pd.DataFrame(ss.base["servers"], columns=service.SERVER_KEYS), num_rows="dynamic",
                use_container_width=True, key=f"servers_{ss.editor_version}",
                column_config={
                    "environment": st.column_config.SelectboxColumn("Ambiente", options=service.ENVIRONMENTS,
                                                                    required=True),
                    "host": st.column_config.TextColumn("Host"),
                    "port": st.column_config.NumberColumn("Porta", min_value=1, max_value=65535, step=1, format="%d"),
                    "database": st.column_config.TextColumn("Service name" if oracle else "Database"),
                    "secretId": st.column_config.TextColumn("Secret (ARN) *", width="large"),
                })
        ss.servers = _records(servers)

    with st.container(border=True):
        st.markdown("##### :material/view_column: Colunas")
        st.caption("Os papéis definem a chave do MERGE, a coluna de data incremental e as colunas criptografadas (LGPD).")
        base_cols = ss.base["columns"]
        keys = ["name", "physicalType", "logicalType", "roles", "description"]
        if any("stagingName" in c for c in base_cols):
            keys.append("stagingName")
        with st.container(key="sec_columns"):
            cols = st.data_editor(
                pd.DataFrame([{**c, "roles": service.roles_of(c)} for c in base_cols], columns=keys),
                num_rows="dynamic", use_container_width=True, key=f"columns_{ss.editor_version}",
                column_config={
                    "name": st.column_config.TextColumn("Coluna *", required=True),
                    "physicalType": st.column_config.TextColumn("Tipo na origem",
                                                                help="Ex: varchar(45), NUMBER(18,0), timestamp"),
                    "logicalType": st.column_config.SelectboxColumn("Tipo lógico", options=service.LOGICAL_TYPES,
                                                                    default="string"),
                    "roles": st.column_config.MultiselectColumn("Papéis", options=list(service.ROLES),
                                                                color=ROLE_COLORS, help=ROLES_HELP, width="medium"),
                    "description": st.column_config.TextColumn("Descrição", width="large"),
                    "stagingName": st.column_config.TextColumn("Nome na staging", help="Opcional: a etapa 2 propõe"),
                })
        ss.columns = [service.with_roles(c, _as_list(c.get("roles"))) for c in _records(cols)
                      if str(c.get("name") or "").strip()]
        names = [c["name"] for c in ss.columns]

    with st.container(border=True):
        st.markdown("##### :material/move_to_inbox: Carga e destino")
        c1, c2, c3 = st.columns(3)
        with c1:
            bound(st.radio, "Tipo de carga", "loadMode", options=["incremental", "full"], horizontal=True,
                  help="incremental: filtra o dia pela coluna incremental. full: tabela inteira.")
        with c2:
            if ss.form["loadMode"] == "incremental":
                partitioned = {c["name"] for c in ss.columns if c.get("partitioned")}
                options = [n for n in names if n not in partitioned]
                ss.form["incrementalColumns"] = [c for c in ss.form.get("incrementalColumns") or [] if c in options]
                bound(st.multiselect, "Colunas extras no filtro (OR)", "incrementalColumns", options=options,
                      help="Ex: data de atualização")
        with c3:
            ss.form["numQueriesParallel"] = int(ss.form.get("numQueriesParallel") or 1)
            bound(st.number_input, "Leitura paralela (queries)", "numQueriesParallel", min_value=1, max_value=64)
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            field_input("Coluna de partição da raw *", "rawPartitionColumn", placeholder="dt_ingestao")
        with c2:
            field_input("Database da raw", "rawDatabase", "Vazio = raw_<dataset>.")
        with c3:
            dataset, table = ss.form.get("dataset") or "<dataset>", ss.form.get("table") or "<tabela>"
            st.markdown(f"**Destino na raw**  \n`<bucket da raw>/{dataset}/{table}/`")
            st.caption("Sempre dataset/tabela. O bucket é informado na execução do orquestrador (--raw-bucket).")
        if any(c.get("encrypt") for c in ss.columns):
            field_input("Secret da chave de criptografia (ARN) *", "cryptographySecretArn")

        c1, c2 = st.columns(2)
        with c1:
            bound(st.checkbox, "Bloquear a carga se a chave vier duplicada", "qualityUniqueKey")
        with c2:
            bound(st.checkbox, "Avisar se a carga vier vazia", "qualityNotEmpty")

    missing = [label for label, ok in [("dataset", ss.form.get("dataset")), ("tabela", ss.form.get("table")),
                                       ("colunas", ss.columns)] if not ok]
    st.button("Próximo: campos e nomenclatura", icon=":material/arrow_forward:", type="primary",
              disabled=bool(missing), on_click=cb_to_fields)
    if missing:
        st.caption(f"Falta preencher: {', '.join(missing)}.")


# ── Etapa 2: Campos e nomenclatura ─────────────────────────────────────

_NAMING_KEYS = ["staging_field", "comment"]


def _naming_filter(rows: list[dict], name: str) -> list[dict]:
    if name == "Renomeadas":
        return [r for r in rows if r["staging_field"] != r["raw_field"].lower()]
    if name == "Editadas por você":
        return [r for r in rows if r["staging_field"] != ss.proposals.get(r["raw_field"], r["staging_field"])]
    if name == "Sensíveis":
        return [r for r in rows if r.get("encrypt")]
    return rows


def step_fields():
    n = ss.naming
    labels = {"llm": "LLM", "heuristica": "glossário (heurística)", "contrato": "data contract", "arquivo": "arquivo"}
    source = " + ".join(labels.get(s, s) for s in (n.source if n else "").split("+") if s)
    rows = ss.naming_rows

    m = st.columns(4)
    m[0].metric("Colunas", len(rows), border=True)
    m[1].metric("Renomeadas", len(_naming_filter(rows, "Renomeadas")), border=True)
    m[2].metric("Editadas por você", len(_naming_filter(rows, "Editadas por você")), border=True)
    m[3].metric("LGPD", len(_naming_filter(rows, "Sensíveis")), border=True)

    st.caption(f"Nomes sugeridos por **{source or '—'}**. A coluna Sugestão guarda o que foi proposto; "
               "o que você alterar em Nome na staging fica gravado no contrato (stagingName).")
    for w in (n.warnings if n else []):
        st.warning(w)

    flt = ss.get("naming_filter", "Todas")
    filters = st.container(horizontal=True, gap="small")
    for name in NAMING_FILTERS:
        filters.button(name, key=f"flt_{name}", type="primary" if name == flt else "secondary",
                       on_click=cb_naming_filter, args=(name,))
    roles = {c["name"]: service.roles_of(c) for c in ss.columns}
    view = [{"sel": r["raw_field"] in ss.selected, "raw_field": r["raw_field"], "data_type": r["data_type"],
             "roles": roles.get(r["raw_field"], []), "suggestion": ss.proposals.get(r["raw_field"], ""),
             "staging_field": r["staging_field"], "comment": r["comment"]}
            for r in _naming_filter(ss.base["naming_rows"], flt)]
    with st.container(key="sec_naming"):
        edited = st.data_editor(
            pd.DataFrame(view, columns=["sel", "raw_field", "data_type", "roles", "suggestion", "staging_field",
                                        "comment"]),
            use_container_width=True, hide_index=True, key=f"naming_{ss.editor_version}_{flt}",
            disabled=["raw_field", "data_type", "roles", "suggestion"],
            column_config={
                "sel": st.column_config.CheckboxColumn("", width=40, help="Marque para as ações abaixo"),
                "raw_field": st.column_config.TextColumn("Coluna na origem"),
                "data_type": st.column_config.TextColumn("Tipo Spark"),
                "roles": st.column_config.MultiselectColumn("Papéis", options=list(service.ROLES),
                                                            color=ROLE_COLORS, help=ROLES_HELP),
                "suggestion": st.column_config.TextColumn("Sugestão", help="Nome proposto pela LLM/glossário"),
                "staging_field": st.column_config.TextColumn("Nome na staging", required=True),
                "comment": st.column_config.TextColumn("Descrição", width="large"),
            })
    changes = {r["raw_field"]: r for r in _records(edited)}
    ss.selected = {raw for raw, r in changes.items() if r.get("sel")} | (ss.selected - set(changes))
    ss.naming_rows = [{**r, **{k: changes[r["raw_field"]][k] for k in _NAMING_KEYS}} if r["raw_field"] in changes
                      else r for r in rows]

    actions = st.container(horizontal=True)
    label = f" ({len(ss.selected)})" if ss.selected else ""
    actions.button(f"Voltar à sugestão{label}", icon=":material/undo:", on_click=cb_rename_selected, args=(False,),
                   help="Desfaz as suas edições nas linhas marcadas")
    actions.button(f"Usar nome da origem{label}", icon=":material/block:", on_click=cb_rename_selected, args=(True,),
                   help="Rejeita a sugestão nas linhas marcadas: o nome na staging fica igual ao da origem")
    actions.button("Sugerir de novo", icon=":material/refresh:", on_click=cb_resuggest,
                   help="Descarta todas as edições e propõe os nomes outra vez")

    st.divider()
    nav = st.container(horizontal=True)
    nav.button("Voltar", icon=":material/arrow_back:", on_click=cb_nav, args=(0,))
    nav.button("Próximo: validar", icon=":material/arrow_forward:", type="primary", on_click=cb_validate)


# ── Etapa 3: Validação ─────────────────────────────────────────────────

def step_validation():
    if ss.validation is None:
        ss.validation = service.validate(current_contract())
    v = ss.validation
    errors = sum(c.level == "error" for c in v.checks)
    warnings = sum(c.level == "warning" for c in v.checks)
    if errors:
        st.error(f"{errors} problema(s) impedem a geração. Use Corrigir para ir até o campo.")
    elif warnings:
        st.warning(f"Tudo certo para gerar, com {warnings} aviso(s).")
    else:
        st.success("Tudo certo para gerar.")

    left, right = st.columns([1, 1.4], gap="large")
    with left, st.container(border=True):
        st.markdown("**Checklist**")
        checklist(v.checks, "checks")
    with right, st.container(border=True):
        st.markdown("**Pré-visualização**")
        tabs = st.tabs(["Data contract", "ingestion.yml", "Transformação"])
        with tabs[0]:
            st.code(service.dump_contract(current_contract()), language="yaml", height=420)
        ingestion = {k: c for k, c in v.files.items() if k.endswith(".ingestion.yml")}
        with tabs[1]:
            if ingestion:
                st.code(next(iter(ingestion.values())), language="yaml", height=420)
            else:
                st.caption("Disponível depois de corrigir os erros.")
        with tabs[2]:
            transform = sorted(k for k in v.files if k not in ingestion)
            if transform:
                model = next((k for k in transform if k.endswith("Model.scala") and "/processor/" in k), None)
                st.caption(f"{len(transform)} arquivos")
                st.code("\n".join(transform), language="text")
                if model:
                    st.code(v.files[model], language="scala")
            else:
                st.caption("Disponível depois de corrigir os erros.")

    st.divider()
    nav = st.container(horizontal=True)
    nav.button("Contrato", icon=":material/arrow_back:", on_click=cb_nav, args=(0,))
    nav.button("Campos", icon=":material/arrow_back:", on_click=cb_nav, args=(1,))
    nav.button("Validar de novo", icon=":material/refresh:", on_click=cb_validate)
    nav.button("Próximo: gerar", icon=":material/arrow_forward:", type="primary", disabled=not v.ok,
               on_click=cb_nav, args=(3,))


# ── Etapa 4: Geração ───────────────────────────────────────────────────

def _zip(base, files: list[str], contract_path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(contract_path, contract_path.relative_to(base).as_posix())
        for rel in files:
            path = base / rel
            if path.exists():
                zf.write(path, rel)
    return buf.getvalue()


def step_generation():
    dataset, table = ss.form["dataset"], ss.form["table"]
    if ss.result is None:
        with st.container(border=True):
            st.markdown("##### :material/folder_open: Onde gravar")
            st.text_input("Pasta de saída", key="out_dir", placeholder=service.default_output_dir(),
                          help=f"Vazio = {service.default_output_dir()}. Use uma pasta de trabalho, não a pasta do framework.")
            st.checkbox("Enviar o ingestion.yml para o S3", key="publish")
            if ss.get("publish"):
                st.text_input("Prefixo S3", key="publish_prefix", placeholder="s3://bucket/ingestion-config/")
            st.markdown(
                "Serão gravados na pasta:\n"
                f"- `contracts/{dataset}/{table}.odcs.yaml` — o data contract\n"
                f"- `ingestion-config/{dataset}/{table}.ingestion.yml` — para o orquestrador\n"
                f"- `{dataset}-transformation/` — projeto da transformação (com git init)\n"
                "- `naming/` — nomenclatura revisada")
        bad_prefix = bool(ss.get("publish")) and not str(ss.get("publish_prefix", "")).startswith("s3://")
        nav = st.container(horizontal=True)
        nav.button("Voltar", icon=":material/arrow_back:", on_click=cb_nav, args=(2,))
        nav.button("Gerar arquivos", icon=":material/rocket_launch:", type="primary", disabled=bad_prefix,
                   on_click=cb_generate)
        return

    r = ss.result
    st.success(f"Pronto! {len(r.files) + 1} arquivos gravados em `{r.output_dir}`.")
    for uri in r.published:
        st.info(f"Enviado para {uri}")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Data contract (.odcs.yaml)", r.contract_path.read_bytes(), r.contract_path.name,
                           icon=":material/download:", use_container_width=True)
    ingestion = next((f for f in r.files if f.endswith(".ingestion.yml")), None)
    with c2:
        if ingestion:
            st.download_button("ingestion.yml", (r.output_dir / ingestion).read_bytes(), ingestion.split("/")[-1],
                               icon=":material/download:", use_container_width=True)
    with c3:
        st.download_button("Tudo (.zip)", _zip(r.output_dir, r.files, r.contract_path), f"{dataset}-{table}.zip",
                           icon=":material/folder_zip:", use_container_width=True)
    st.markdown("**Próximos passos:** envie o `ingestion.yml` ao S3 lido pelo orquestrador (se ainda não enviou) e "
                f"compile e suba o projeto `{dataset}-transformation`.")
    with st.expander("Arquivos gerados"):
        st.code("\n".join([r.contract_path.relative_to(r.output_dir).as_posix(), *r.files]), language="text")
    with st.expander("Log da geração"):
        st.code(r.log or "(vazio)", language="text")
    st.button("Criar outro contrato", type="primary", on_click=cb_reset)


# ── Tela ───────────────────────────────────────────────────────────────

top = st.container(horizontal=True, vertical_alignment="center")
if ss.flash:
    level, message = ss.flash
    getattr(st, level)(message)
    ss.flash = None

STEP_VIEWS = [step_contract, step_fields, step_validation, step_generation]
if ss.step <= 1:
    main, side = st.columns([2.2, 1], gap="large")
    with main:
        STEP_VIEWS[ss.step]()
    contract = current_contract(with_naming=ss.step == 1)
    checks = service.health_checks(contract)
    with side:
        preview_panel(service.dump_contract(contract), checks)
else:
    STEP_VIEWS[ss.step]()
    checks = service.health_checks(current_contract())
    if ss.validation is not None and ss.step == 2:
        checks = ss.validation.checks
highlight_focus(checks)

# Barra do topo: dataset / tabela e o status do contrato
pending = sum(c.level == "error" for c in checks)
dataset, table = ss.form.get("dataset") or "dataset", ss.form.get("table") or "tabela"
top.markdown(f"#### :material/contract: :gray[{dataset} /] {table}", width="content")
if ss.result is not None:
    top.badge("gerado", icon=":material/check:", color="green")
elif pending:
    top.badge(f"{pending} pendência(s)", icon=":material/error:", color="red")
elif ss.validation is not None and ss.validation.ok:
    top.badge("válido", icon=":material/verified:", color="green")
else:
    top.badge("rascunho", icon=":material/edit_note:", color="orange")

with st.sidebar:
    st.title("Data Contract Studio")
    st.caption("Crie o data contract da tabela e gere o ingestion.yml e o projeto de transformação.")
    can_generate = ss.validation is not None and ss.validation.ok
    for i, (title, sub, icon) in enumerate(STEPS):
        done = i < ss.step
        label = f"{i + 1}. {title}" + (f"  ·  {pending}" if i == 2 and pending else "")
        st.button(label, key=f"nav_{i}", help=sub, icon=":material/check_circle:" if done else icon,
                  type="primary" if i == ss.step else "tertiary", use_container_width=True,
                  disabled=i > ss.max_step + 1 or (i == 3 and not can_generate) or (i == 1 and not ss.columns),
                  on_click=cb_nav, args=(i,))
    st.divider()
    st.text_input("Modelo de LLM para a nomenclatura", key="llm_model",
                  help="Ex: litellm:claude-sonnet-5-5. Vazio = heurística por glossário.")
    level, message = llm_status(ss.llm_model)
    {"ok": st.success, "warning": st.warning, "error": st.error}.get(level, st.caption)(
        message, **({"icon": LLM_ICONS[level]} if level in LLM_ICONS else {}))
    st.button("Começar um novo contrato", icon=":material/restart_alt:", use_container_width=True, on_click=cb_reset)

"""Data Contract Studio — interface do framework (dl-gen ui).

Linha do tempo: 1. Contrato → 2. Campos e nomenclatura → 3. Validação → 4. Geração.
A lógica fica em framework.ui.service; aqui só a tela. Os botões usam callbacks (on_click):
eles rodam antes da tela ser desenhada, então a navegação não precisa de st.rerun().
"""

from __future__ import annotations

import io
import math
import os
import zipfile

import pandas as pd
import streamlit as st

from framework.llm import resolve_model_name
from framework.ui import service

st.set_page_config(page_title="Data Contract Studio", page_icon="📄", layout="wide")

STEPS = [
    ("Contrato", "Tabela, origem e destino"),
    ("Campos", "Nomenclatura da transformação"),
    ("Validação", "Conferência antes de gerar"),
    ("Geração", "Contrato, ingestion.yml e transformação"),
]

st.markdown("""
<style>
.timeline { display: flex; align-items: flex-start; margin: 0.5rem 0 1.5rem; }
.tl-step { display: flex; flex-direction: column; align-items: center; width: 150px; text-align: center; }
.tl-dot { width: 38px; height: 38px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
          font-weight: 700; font-size: 1rem; border: 2px solid #cbd5e1; color: #64748b; background: transparent; }
.tl-step.done .tl-dot { background: #16a34a; border-color: #16a34a; color: #fff; }
.tl-step.current .tl-dot { background: #2563eb; border-color: #2563eb; color: #fff; box-shadow: 0 0 0 5px rgba(37,99,235,.18); }
.tl-title { margin-top: .45rem; font-weight: 600; font-size: .95rem; }
.tl-sub { font-size: .78rem; opacity: .65; }
.tl-step.pending .tl-title { opacity: .55; }
.tl-line { flex: 1; height: 3px; background: #cbd5e1; margin-top: 18px; border-radius: 2px; min-width: 30px; }
.tl-line.done { background: #16a34a; }
.check { padding: .45rem .7rem; border-radius: 8px; margin-bottom: .35rem; border-left: 4px solid; }
.check.ok { border-color: #16a34a; background: rgba(22,163,74,.08); }
.check.warning { border-color: #d97706; background: rgba(217,119,6,.10); }
.check.error { border-color: #dc2626; background: rgba(220,38,38,.10); }
.check small { display: block; opacity: .8; margin-top: .1rem; }
</style>
""", unsafe_allow_html=True)


# ── Estado ─────────────────────────────────────────────────────────────

ss = st.session_state
ss.setdefault("step", 0)
ss.setdefault("form", service.empty_form())
ss.setdefault("servers", service.empty_servers())
ss.setdefault("columns", [])
ss.setdefault("naming", None)       # NamingResult
ss.setdefault("naming_rows", [])
ss.setdefault("validation", None)   # ValidationResult
ss.setdefault("result", None)       # GenerationResult
ss.setdefault("flash", None)        # (nível, mensagem) mostrada uma vez
ss.setdefault("editor_version", 0)  # muda quando as tabelas editáveis precisam recarregar
# Base das tabelas editáveis: só muda ao trocar de etapa/importar (o editor guarda as edições sobre ela)
ss.setdefault("base", {"servers": ss.servers, "columns": ss.columns, "naming_rows": ss.naming_rows})
ss.setdefault("out_dir", os.getcwd())
ss.setdefault("llm_model", resolve_model_name(""))


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame do editor → lista de dicts sem NaN."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}
            for r in df.to_dict("records")]


def _go(step: int, reload_widgets: bool = False):
    """Troca de etapa (chamada dentro de callbacks). reload_widgets: os dados mudaram por fora (importação)."""
    ss.step = step
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


def cb_validate():
    ss.validation = service.validate(current_contract())
    _go(2)


def cb_back(step: int):
    _go(step)


def cb_generate():
    prefix = ss.get("publish_prefix", "") if ss.get("publish") else ""
    try:
        ss.result = service.generate(current_contract(), ss.out_dir, ss.llm_model, prefix)
    except Exception as e:  # noqa: BLE001
        _flash("error", f"Falha na geração: {e}")


# ── Componentes ────────────────────────────────────────────────────────

def timeline(current: int):
    parts = []
    for i, (title, sub) in enumerate(STEPS):
        state = "done" if i < current else "current" if i == current else "pending"
        mark = "✓" if state == "done" else str(i + 1)
        if i:
            parts.append(f'<div class="tl-line {"done" if i <= current else ""}"></div>')
        parts.append(f'<div class="tl-step {state}"><div class="tl-dot">{mark}</div>'
                     f'<div class="tl-title">{title}</div><div class="tl-sub">{sub}</div></div>')
    st.markdown(f'<div class="timeline">{"".join(parts)}</div>', unsafe_allow_html=True)


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


# ── Barra lateral ──────────────────────────────────────────────────────

with st.sidebar:
    st.header("📄 Data Contract Studio")
    st.caption("Crie o data contract da tabela e gere o ingestion.yml e o projeto de transformação.")
    st.text_input("Modelo de LLM para a nomenclatura", key="llm_model",
                  help="Ex: litellm:claude-sonnet-5-5. Vazio = heurística por glossário.")
    if not ss.llm_model:
        st.caption("Sem LLM: os nomes vêm do glossário (heurística).")
    st.divider()
    st.button("🗑️ Começar um novo contrato", use_container_width=True, on_click=cb_reset)

st.title("Data Contract Studio")
timeline(ss.step)
if ss.flash:
    level, message = ss.flash
    getattr(st, level)(message)
    ss.flash = None


# ── Etapa 1: Contrato ──────────────────────────────────────────────────

def step_contract():
    with st.expander("⚡ Preencher a partir de uma DDL ou de um contrato existente", expanded=not ss.columns):
        tab_ddl, tab_contract = st.tabs(["Colar DDL (CREATE TABLE)", "Abrir data contract (.odcs.yaml)"])
        with tab_ddl:
            st.text_area("DDL", key="ddl_text", height=160, label_visibility="collapsed",
                         placeholder="CREATE TABLE public.cliente (\n  id INTEGER PRIMARY KEY,\n  ...\n);")
            st.button("Importar colunas da DDL", disabled=not ss.get("ddl_text", "").strip(), on_click=cb_import_ddl)
        with tab_contract:
            st.file_uploader("Data contract", type=["yaml", "yml"], key="upload", label_visibility="collapsed")
            st.button("Carregar contrato", disabled=ss.get("upload") is None, on_click=cb_load_contract)

    st.subheader("Identificação")
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

    st.subheader("Origem")
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
    servers = st.data_editor(
        pd.DataFrame(ss.base["servers"], columns=service.SERVER_KEYS), num_rows="dynamic", use_container_width=True,
        key=f"servers_{ss.editor_version}",
        column_config={
            "environment": st.column_config.SelectboxColumn("Ambiente", options=service.ENVIRONMENTS, required=True),
            "host": st.column_config.TextColumn("Host"),
            "port": st.column_config.NumberColumn("Porta", min_value=1, max_value=65535, step=1, format="%d"),
            "database": st.column_config.TextColumn("Service name" if oracle else "Database"),
            "secretId": st.column_config.TextColumn("Secret (ARN) *", width="large"),
        })
    ss.servers = _records(servers)

    st.subheader("Colunas")
    st.caption("Marque a chave primária (chave do MERGE), a coluna de data incremental e as colunas a criptografar (LGPD).")
    base_cols = ss.base["columns"]
    cols = st.data_editor(
        pd.DataFrame(base_cols, columns=service.COLUMN_KEYS + (["stagingName"] if any("stagingName" in c for c in base_cols) else [])),
        num_rows="dynamic", use_container_width=True, key=f"columns_{ss.editor_version}",
        column_config={
            "name": st.column_config.TextColumn("Coluna *", required=True),
            "physicalType": st.column_config.TextColumn("Tipo na origem", help="Ex: varchar(45), NUMBER(18,0), timestamp"),
            "logicalType": st.column_config.SelectboxColumn("Tipo lógico", options=service.LOGICAL_TYPES, default="string"),
            "primaryKey": st.column_config.CheckboxColumn("Chave", default=False),
            "required": st.column_config.CheckboxColumn("Obrigatória", default=False),
            "partitioned": st.column_config.CheckboxColumn("Incremental", default=False,
                                                           help="Coluna de data do filtro incremental (só uma)"),
            "encrypt": st.column_config.CheckboxColumn("Criptografar", default=False),
            "description": st.column_config.TextColumn("Descrição", width="large"),
            "stagingName": st.column_config.TextColumn("Nome na staging", help="Opcional: a etapa 2 propõe"),
        })
    ss.columns = [c for c in _records(cols) if str(c.get("name") or "").strip()]
    names = [c["name"] for c in ss.columns]

    st.subheader("Carga e destino")
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

    st.divider()
    missing = [label for label, ok in [("dataset", ss.form.get("dataset")), ("tabela", ss.form.get("table")),
                                       ("colunas", ss.columns)] if not ok]
    st.button("Próximo: campos e nomenclatura →", type="primary", disabled=bool(missing), on_click=cb_to_fields)
    if missing:
        st.caption(f"Falta preencher: {', '.join(missing)}.")


# ── Etapa 2: Campos e nomenclatura ─────────────────────────────────────

def step_fields():
    n = ss.naming
    labels = {"llm": "LLM", "heuristica": "glossário (heurística)", "contrato": "data contract", "arquivo": "arquivo"}
    source = " + ".join(labels.get(s, s) for s in (n.source if n else "").split("+") if s)
    st.info(f"Nomes propostos por: **{source or '—'}**. Edite o nome na staging e a descrição; "
            "o que você alterar fica gravado no contrato (stagingName).")
    for w in (n.warnings if n else []):
        st.warning(w)

    rows = st.data_editor(
        pd.DataFrame(ss.base["naming_rows"]), use_container_width=True, hide_index=True,
        key=f"naming_{ss.editor_version}", disabled=["raw_field", "data_type", "primaryKey", "encrypt"],
        column_config={
            "raw_field": st.column_config.TextColumn("Coluna na origem"),
            "data_type": st.column_config.TextColumn("Tipo Spark"),
            "staging_field": st.column_config.TextColumn("Nome na staging ✏️", required=True),
            "comment": st.column_config.TextColumn("Descrição ✏️", width="large"),
            "primaryKey": st.column_config.CheckboxColumn("Chave"),
            "encrypt": st.column_config.CheckboxColumn("Criptografada"),
        })
    ss.naming_rows = _records(rows)

    st.divider()
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        st.button("← Voltar", on_click=cb_back, args=(0,))
    with c2:
        st.button("↻ Sugerir de novo", help="Descarta as edições e propõe os nomes outra vez", on_click=cb_resuggest)
    with c3:
        st.button("Próximo: validar →", type="primary", on_click=cb_validate)


# ── Etapa 3: Validação ─────────────────────────────────────────────────

def step_validation():
    if ss.validation is None:
        ss.validation = service.validate(current_contract())
    v = ss.validation
    icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
    errors = sum(c.level == "error" for c in v.checks)
    warnings = sum(c.level == "warning" for c in v.checks)
    if errors:
        st.error(f"{errors} problema(s) impedem a geração. Volte e corrija.")
    elif warnings:
        st.warning(f"Tudo certo para gerar, com {warnings} aviso(s).")
    else:
        st.success("Tudo certo para gerar.")

    left, right = st.columns([1, 1.4])
    with left:
        st.subheader("Checklist")
        for c in v.checks:
            detail = f"<small>{c.detail}</small>" if c.detail else ""
            st.markdown(f'<div class="check {c.level}">{icons[c.level]} {c.title}{detail}</div>', unsafe_allow_html=True)
    with right:
        st.subheader("Pré-visualização")
        tabs = st.tabs(["Data contract", "ingestion.yml", "Transformação"])
        with tabs[0]:
            st.code(service.dump_contract(current_contract()), language="yaml")
        ingestion = {k: c for k, c in v.files.items() if k.endswith(".ingestion.yml")}
        with tabs[1]:
            if ingestion:
                st.code(next(iter(ingestion.values())), language="yaml")
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
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        st.button("← Contrato", on_click=cb_back, args=(0,))
    with c2:
        st.button("← Campos", on_click=cb_back, args=(1,))
    with c3:
        st.button("↻ Validar de novo", on_click=cb_validate)
    with c4:
        st.button("Próximo: gerar →", type="primary", disabled=not v.ok, on_click=cb_back, args=(3,))


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
        st.subheader("Onde gravar")
        st.text_input("Pasta de saída", key="out_dir", help="Use uma pasta de trabalho, não a pasta do framework.")
        st.checkbox("Enviar o ingestion.yml para o S3", key="publish")
        if ss.get("publish"):
            st.text_input("Prefixo S3", key="publish_prefix", placeholder="s3://bucket/ingestion-config/")
        st.markdown(
            "Serão gravados na pasta:\n"
            f"- `contracts/{dataset}/{table}.odcs.yaml` — o data contract\n"
            f"- `ingestion-config/{dataset}/{table}.ingestion.yml` — para o orquestrador\n"
            f"- `{dataset}-transformation/` — projeto Scala da transformação (com git init)\n"
            "- `naming/` — nomenclatura revisada")
        bad_prefix = bool(ss.get("publish")) and not str(ss.get("publish_prefix", "")).startswith("s3://")
        c1, c2 = st.columns([1, 4])
        with c1:
            st.button("← Voltar", on_click=cb_back, args=(2,))
        with c2:
            st.button("Gerar arquivos", type="primary", disabled=bad_prefix, on_click=cb_generate)
        return

    r = ss.result
    st.success(f"Pronto! {len(r.files) + 1} arquivos gravados em `{r.output_dir}`.")
    for uri in r.published:
        st.info(f"Enviado para {uri}")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("⬇️ Data contract (.odcs.yaml)", r.contract_path.read_bytes(), r.contract_path.name,
                           use_container_width=True)
    ingestion = next((f for f in r.files if f.endswith(".ingestion.yml")), None)
    with c2:
        if ingestion:
            st.download_button("⬇️ ingestion.yml", (r.output_dir / ingestion).read_bytes(), ingestion.split("/")[-1],
                               use_container_width=True)
    with c3:
        st.download_button("⬇️ Tudo (.zip)", _zip(r.output_dir, r.files, r.contract_path), f"{dataset}-{table}.zip",
                           use_container_width=True)
    st.markdown("**Próximos passos:** envie o `ingestion.yml` ao S3 lido pelo orquestrador (se ainda não enviou) e "
                f"compile e suba o projeto `{dataset}-transformation`.")
    with st.expander("Arquivos gerados"):
        st.code("\n".join([r.contract_path.relative_to(r.output_dir).as_posix(), *r.files]), language="text")
    with st.expander("Log da geração"):
        st.code(r.log or "(vazio)", language="text")
    st.button("Criar outro contrato", type="primary", on_click=cb_reset)


[step_contract, step_fields, step_validation, step_generation][ss.step]()

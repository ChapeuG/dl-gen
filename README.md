# Data Lake Framework (`dl-gen`)

Gera, a partir do **data contract** de uma tabela (ou do DDL, de uma query ou de qualquer schema com nome e tipo dos
campos: Avro, JSON Schema, planilha, parquet...):

- o `ingestion.yml` usado pelo [`ingestion-orchestrator`](https://github.com/ChapeuG/ingestion-orchestrator);
- o projeto de transformação `<dataset>-transformation` (raw → staging Delta), em **PySpark** (padrão) ou **Scala** (`--language scala`).

```powershell
git clone https://github.com/ChapeuG/dl-gen.git
cd dl-gen
pip install -e ".[ui]"

dl-gen ui                                   # interface: contrato → campos → validação → geração
dl-gen generate --contract actor.odcs.yaml  # ou pela linha de comando
```

Passo a passo completo: **[MANUAL.md](MANUAL.md)**.

O que cada etapa sabe fazer está nas **[skills do agente](src/framework/skills/README.md)** (`src/framework/skills/`,
um `SKILL.md` por skill; `dl-gen skills` lista). Nomes de coluna com LLM usam o LiteLLM pela lib `openai`
(`dl-gen llm` testa a conexão).

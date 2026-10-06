# Data Lake Framework (`dl-gen`)

Gera, a partir do **data contract** (ou do DDL) de uma tabela:

- o `ingestion.yml` usado pelo [`ingestion-orchestrator`](https://github.com/ChapeuG/ingestion-orchestrator);
- o projeto Scala de transformação `<dataset>-transformation` (raw → staging Delta).

```powershell
git clone https://github.com/ChapeuG/dl-gen.git
cd dl-gen
pip install -e ".[ui]"

dl-gen ui                                   # interface: contrato → campos → validação → geração
dl-gen generate --contract actor.odcs.yaml  # ou pela linha de comando
```

Passo a passo completo: **[MANUAL.md](MANUAL.md)**.

# Data Lake Framework (`dl-gen`)

Gera, a partir do **data contract** (ou do DDL) de uma tabela:

- o `ingestion.yml` usado pelo [`ingestion-orchestrator`](../../ingestion-orchestrator/README.md);
- o projeto Scala de transformação `<dataset>-transformation` (raw → staging Delta).

```powershell
pip install -e .
dl-gen generate --contract actor.odcs.yaml
```

Passo a passo completo: **[MANUAL.md](MANUAL.md)**.

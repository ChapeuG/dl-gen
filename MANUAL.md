# Manual — Data Lake Framework (`dl-gen`)

## O que ele faz

Você descreve uma tabela (num **data contract** ou num **DDL**) e o framework gera tudo o que é preciso para ela chegar
ao Data Lake:

```
 data contract (.odcs.yaml)  ou  DDL (.sql)
                │
                ▼
          dl-gen generate
                │
     ┌──────────┴──────────────┐
     ▼                         ▼
 INGESTÃO                   TRANSFORMAÇÃO
 ingestion.yml              projeto Scala <dataset>-transformation
 (lido pelo orquestrador)   (raw → staging Delta + tabela Hive)
```

- **Ingestão:** sai um arquivo `ingestion.yml`, que o projeto
  [`ingestion-orchestrator`](https://github.com/ChapeuG/ingestion-orchestrator) usa para ler a origem e gravar na raw.
- **Transformação:** sempre sai o projeto Scala `<dataset>-transformation`, no padrão das skills da empresa.

---

## 1. Instalar (uma vez só)

Precisa de **Python 3.10+**. Para compilar os projetos Scala gerados, também do **sbt** (sem ele os projetos são
gravados, mas não compilados).

```powershell
git clone https://github.com/ChapeuG/dl-gen.git
cd dl-gen
pip install -e ".[ui]"
```

Pronto: o comando `dl-gen` passa a funcionar em qualquer pasta. (`[ui]` instala a interface; sem ela, use
`pip install -e .`.)

---

## 2. Jeito mais fácil: a interface (Data Contract Studio)

Abra o terminal numa **pasta de trabalho** e rode:

```powershell
dl-gen ui
```

O navegador abre em `http://localhost:8501` com uma linha do tempo de 4 etapas:

| Etapa | O que você faz |
|---|---|
| **1. Contrato** | Cola a DDL (ou abre um `.odcs.yaml`) para trazer as colunas, e preenche dataset, origem por ambiente (host, secret) e coluna de partição da raw. O destino na raw é sempre `<bucket>/<dataset>/<tabela>/`. Na tabela de colunas, marca a chave, a coluna incremental e o que criptografar. |
| **2. Campos** | Recebe os campos com o **nome na staging** e a descrição propostos para a transformação. Edite o que quiser direto na tabela. |
| **3. Validação** | Vê um checklist (✅ ok, ⚠️ aviso, ❌ erro) e a prévia do contrato, do `ingestion.yml` e da transformação. Com erro, o botão de gerar fica bloqueado. |
| **4. Geração** | Escolhe a pasta de saída (e, se quiser, o prefixo S3) e clica em **Gerar arquivos**. Baixa o contrato, o `ingestion.yml` ou tudo em `.zip`. |

O que é gravado na pasta de saída: `contracts/<dataset>/<tabela>.odcs.yaml`, `ingestion-config/...`,
`<dataset>-transformation/` e `naming/`. Para usar LLM na nomenclatura, informe o modelo na barra lateral
(veja a seção 5).

O passo a passo abaixo faz a mesma coisa pela linha de comando.

---

## 3. Passo a passo pela linha de comando

### Passo 1 — Escrever o contrato da tabela

O template e os exemplos ficam no projeto do orquestrador:

```powershell
git clone https://github.com/ChapeuG/ingestion-orchestrator.git
cd ingestion-orchestrator
python scripts\novo_contrato.py sakila actor --domain exemplos
```

Isso cria `contracts\sakila\actor.odcs.yaml`. Abra o arquivo e troque tudo que está como `<...>`. Os comentários
explicam cada campo: `[OBRIGATÓRIO]` precisa ser preenchido, `[EXT]` é uma regra nossa.

O mínimo que o contrato precisa ter:

| O quê | Onde no contrato |
|---|---|
| Nome do dataset | `dataProduct` |
| Banco de origem e a secret com usuário/senha | `servers[]`: `type`, `environment`, `host`, `port`, `database` e `secretId` |
| Tabela e colunas | `schema[].name`, `physicalName`, `properties[]` |
| Chave da tabela | `primaryKey: true` na(s) coluna(s) |
| Coluna de data para a carga incremental | `partitioned: true` |
| Coluna de partição da raw | `rawPartitionColumn` (sem valor padrão) |

Para editar visualmente (opcional): `npx datacontract-editor contracts\sakila\actor.odcs.yaml`.

### Passo 2 — Gerar

Abra o terminal numa **pasta de trabalho** (os projetos são criados na pasta atual; não use a pasta do framework) e
passe o **caminho completo** do contrato:

```powershell
cd C:\trabalho\minha-tabela
dl-gen generate --contract C:\caminho\do\ingestion-orchestrator\contracts\sakila\actor.odcs.yaml
```

> Erro `Path '...' does not exist`: o caminho relativo não existe na pasta onde o terminal está. Use o caminho completo.

Modelo pronto para testar: `framework\exemplos\cred_final.odcs.yaml` (gerado a partir de `exemplos\cred_final.sql`).

Sai isto na pasta atual:

```
ingestion-config\sakila\actor.ingestion.yml     ← ingestão (para o orquestrador)
sakila-transformation\                          ← projeto Scala da transformação (já com git init)
naming\actor.json                               ← nomes das colunas na staging, para você revisar
```

Para testar sem gravar nada, acrescente `--dry-run`.

### Passo 3 — Revisar os nomes das colunas

O framework traduz cada coluna para o **padrão de nomenclatura** (ex: `trade_name` → `nm_fantasia`). Confira em
`naming\actor.json`: se algum nome estiver errado, corrija no arquivo e rode o **Passo 2** de novo. O arquivo passa a
valer nas próximas execuções.

Para fixar o nome direto no contrato, use `stagingName` na coluna. Ele vale mais que o arquivo.

> Se aparecer `PREENCHER` no aviso do terminal, falta um campo obrigatório no contrato. Complete e gere de novo.

### Passo 4 — Publicar o ingestion.yml no S3

```powershell
dl-gen generate --contract C:\...\actor.odcs.yaml --publish-s3 s3://<bucket>/ingestion-config/
```

Ou envie depois: `aws s3 cp ingestion-config\sakila\actor.ingestion.yml s3://<bucket>/ingestion-config/sakila/`.

### Passo 5 — Rodar a ingestão

Quem roda é o orquestrador (projeto separado). Veja o README dele. Em resumo:

```
spark-submit ... jobs/main.py --config s3://<bucket>/ingestion-config/sakila/actor.ingestion.yml --env prd
```

### Passo 6 — Subir a transformação

```powershell
cd sakila-transformation
sbt compile
git add . ; git commit -m "Transformação actor" ; git push
```

O repositório já sai com `.github/workflows/pipeline.yml` (GitHub → CodeCommit), `catalog-info.yaml` e o SDD em
`docs_sdd\actor_sdd_doc.md`. Complete as seções pendentes do SDD.

---

## 4. Outros jeitos de usar

**Sem contrato, só com o DDL** (o que o DDL não informa vai por opção):
```powershell
dl-gen generate --ddl C:\caminho\do\dl-gen\exemplos\cred_final.sql --dataset previsao --merge-keys cd_credenciadora,nm_produto,data
```
No modo contrato, o yml sai com `PREENCHER` onde faltar informação (servidor, secret, destino). Por isso, para a
ingestão nova, prefira o contrato.

**Várias tabelas no mesmo projeto de transformação:** gere a primeira normalmente e as próximas com `--append`.

**Só o bloco de campos (`ModelField`) para colar num Model existente:**
```powershell
dl-gen campos --ddl C:\caminho\do\dl-gen\exemplos\cred_final.sql -o Field.scala
```

---

## 5. Nomes das colunas com LLM (opcional)

Sem LLM, os nomes saem de um glossário (heurística). Com LLM ficam melhores. O framework sempre confere o resultado
contra o padrão de nomenclatura e, se o LLM falhar, volta para a heurística sozinho.

- **LiteLLM:** a URL e a chave são lidas de `C:\Users\<matricula>\.claude\settings.json`, no bloco
  `env` (`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_API_KEY`, ou `LITELLM_BASE_URL` + `LITELLM_API_KEY`)
  ou no `apiKeyHelper`.
  ```powershell
  dl-gen generate --contract actor.odcs.yaml --llm-model litellm:<modelo>
  ```
  Se o `settings.json` tiver `ANTHROPIC_MODEL`, o LLM liga sem precisar do `--llm-model`.
- **Outros provedores:** `--llm-model openai:gpt-4o-mini`, `anthropic:...`, `bedrock:...` (com a chave do provedor).

No fim da execução, a nomenclatura mostra a fonte usada: `contrato`, `arquivo`, `llm` ou `heuristica`.

---

## 6. Todas as opções do `generate`

Com `--contract`, quase tudo vem do contrato. As opções servem para **sobrescrever** o que o contrato diz.

| Opção | Para que serve | Default |
|---|---|---|
| `--contract` | Data contract ODCS (`.odcs.yaml`) | — |
| `--table` | Qual tabela do contrato (se tiver mais de uma) | a única |
| `--ddl` | DDL `CREATE TABLE` (no lugar do contrato) | — |
| `--publish-s3` | Envia o yml para este prefixo S3 | não envia |
| `--dataset` | Nome do dataset | `dataProduct` do contrato (obrigatório com `--ddl`) |
| `--source-db` | `postgres`, `oracle`, `mysql`, `sqlserver` | `servers[].type` do contrato |
| `--partition-col` | Coluna de data da carga incremental | `partitioned: true` / `created_at` |
| `--merge-keys` | Chave do MERGE na transformação | `primaryKey` / PK do DDL |
| `--encrypt` | Colunas criptografadas na ingestão (LGPD) | `encrypt: true` no contrato |
| `--llm-model` | Modelo para os nomes das colunas | heurística |
| `--sample` | Amostra (`.csv`, `.json`, `.parquet`): ajuda a detectar centavos e dados sensíveis | — |
| `--tipagem` | Planilha Tipo Origem → Tipo Final | tabela oficial embutida |
| `--naming-dir` | Pasta dos arquivos de nomenclatura | `naming` |
| `--output-dir` | Onde criar os projetos | pasta atual |
| `--append` | Acrescenta a tabela num projeto de transformação existente | — |
| `--skip-input` | Gera só a transformação | — |
| `--dry-run` | Mostra o que seria gerado, sem gravar | — |
| `--github-org`, `--codecommit-transformation` | Repositórios do pipeline | `datalake-org`, `<dataset>-...` |

Regras que o framework aplica sozinho:
- **Criptografia:** as colunas marcadas são criptografadas (AES/ECB + base64) **antes** de gravar na raw. Na
  transformação, elas ficam sem transformação.
- **Sem coluna de data:** a carga vira full.
- **Sem chave:** se não houver PK, `--merge-keys` nem coluna NOT NULL, a geração para com erro.
- **Dado sensível sem criptografia:** o terminal avisa (cpf, cnpj, email...).

---

## 7. Problemas comuns

| Problema | O que fazer |
|---|---|
| `Path '...' does not exist` | O caminho é relativo à pasta do terminal. Use o caminho completo do arquivo |
| `dl-gen` não é reconhecido | Rode `pip install -e ".[ui]"` de novo na pasta do framework |
| `dl-gen ui` diz que falta o Streamlit | `pip install -e ".[ui]"` |
| `UnicodeEncodeError` no terminal | Rode `$env:PYTHONUTF8 = "1"` no PowerShell antes do comando |
| `sbt não encontrado` | Os projetos foram gravados, só não compilados. Instale o sbt para compilar |
| Aviso de `PREENCHER` | Falta um campo obrigatório no contrato. Complete e gere de novo |
| `O contrato tem N tabelas; informe --table` | Use `--table <nome>` |
| Nome de coluna ruim | Corrija em `naming\<tabela>.json` (ou `stagingName` no contrato) e gere de novo |
| `LLM indisponível` | A heurística assumiu. Confira a chave do LiteLLM no `settings.json` |

---

## 8. Para quem mexe no código

```powershell
python -m pytest tests -q
```

| Pasta/arquivo | O que tem |
|---|---|
| `src/framework/cli.py` | Comandos `generate`, `campos` e `ui` |
| `src/framework/ui/` | Interface: `app.py` (tela) e `service.py` (lógica testável) |
| `src/framework/graph.py` | Fluxo (LangGraph): profiler → nomenclatura → ingestão ∥ transformação → validação |
| `src/framework/parsers/` | Leitura do contrato (`contract_parser.py`), do DDL e da amostra |
| `src/framework/agents/` | Uma etapa por arquivo (`input_gen.py` gera o ingestion.yml) |
| `src/framework/ingestion_config.py` | Formato do `ingestion.yml` |
| `src/framework/llm.py` | Modelos de LLM (inclui o LiteLLM) |
| `src/framework/standards/` | Padrão de nomenclatura, glossário, tipagem e bancos de origem |
| `src/framework/templates/` | Templates dos projetos gerados |
| `exemplos/` | DDLs de exemplo e o modelo de contrato `cred_final.odcs.yaml` |

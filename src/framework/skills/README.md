# Skills do agente

Biblioteca de referência para gerar e revisar a ingestão e o projeto de transformação Spark + Delta Lake
(`<dataset>-transformation`). Cada skill é um `SKILL.md` (quando usar + regras) e, quando útil, `scripts/` que os
templates do dl-gen **espelham 1:1** (pacote `br.com.datalake`) ou `references/` com os documentos de apoio.

Para listar: `dl-gen skills`. No Studio, a barra lateral mostra as skills em "Skills do agente".

## Fluxo (do schema ao deploy)

1. **leitura-de-schema** — lê os campos e tipos de DDL, query, Avro, JSON Schema, planilha, parquet...
2. **sdd-specification** — especifica a tabela antes de qualquer código (o dl-gen gera o SDD).
3. **data-governance-names** + **data-transformation-patterns** — nomes e transformações dos campos.
4. **ingestao** — o `ingestion.yml` do ingestion-orchestrator.
5. **project-structure** + **processor-orchestration** — onde o código vive e o fluxo do processor.
6. Implementação: **catalyst-optimization**, **timestamp-handling**, **processing-timestamp**,
   **enrichment-joins**, **fact-to-fact-joins**, **nested-field-extraction**,
   **dataframe-persist-strategy**, **delta-write-patterns**, **hive-table-management**.
7. Operação: **job-parameters**, **error-handler**.

## Índice

| Skill | Quando usar | Onde o dl-gen aplica |
|---|---|---|
| [leitura-de-schema](leitura-de-schema/SKILL.md) | Campos vindos de query, Avro, JSON Schema, StructType, lista de campos ou arquivo de dados | `parsers/schema_reader.py` |
| [sdd-specification](sdd-specification/SKILL.md) | Criar/revisar o SDD de uma tabela nova | `templates/transformation/sdd_doc.md.j2` |
| [data-governance-names](data-governance-names/SKILL.md) | Nomear colunas pelo padrão `<mnemônico>_<nome>` | `agents/naming.py` (**prompt do LLM**) |
| [data-transformation-patterns](data-transformation-patterns/SKILL.md) | Transformações de coluna (String/PII/Date/Timestamp) | `agents/transform_gen.py` |
| [ingestao](ingestao/SKILL.md) | Gerar/revisar o `ingestion.yml` | `agents/input_gen.py` |
| [project-structure](project-structure/SKILL.md) | Layout do projeto, pacotes, Main/Model/Processor, utils | `agents/transform_gen.py`, `static/utils` |
| [processor-orchestration](processor-orchestration/SKILL.md) | Processor de ponta a ponta | template do processor |
| [job-parameters](job-parameters/SKILL.md) | Parâmetros do job (core vs opcionais) | `main` + `args_parser` |
| [catalyst-optimization](catalyst-optimization/SKILL.md) | Single-`select`, dispatch por pattern matching | `transform_column` |
| [timestamp-handling](timestamp-handling/SKILL.md) | Parsing de timestamp de origem | `normalize_timestamp` |
| [processing-timestamp](processing-timestamp/SKILL.md) | Run-timestamp no driver e partição de atualização | template do processor |
| [enrichment-joins](enrichment-joins/SKILL.md) | Broadcast join com dimensões pequenas | `apply_enrichment` |
| [fact-to-fact-joins](fact-to-fact-joins/SKILL.md) | Join fato-a-fato particionado | referência (ainda não gerado) |
| [nested-field-extraction](nested-field-extraction/SKILL.md) | Subcampos posicionais (substring/regex) | `nested_field_spec` |
| [dataframe-persist-strategy](dataframe-persist-strategy/SKILL.md) | `persist`/`count`/`unpersist` em torno do MERGE | template do processor |
| [delta-write-patterns](delta-write-patterns/SKILL.md) | Dedup determinístico, merge null-safe, overwrite, manifesto | `delta_write_pattern` |
| [hive-table-management](hive-table-management/SKILL.md) | Tabela externa Hive/Athena, schema evolution, partições | `hive_table_manager` |
| [error-handler](error-handler/SKILL.md) | Classificação de erros Spark e ação sugerida (SQS) | `static/error` |

## Pares importantes (não confundir)

- **timestamp-handling** (parsing de string de origem) × **processing-timestamp** (carimbo de execução).
- **enrichment-joins** (dimensões pequenas, broadcast) × **fact-to-fact-joins** (fatos grandes, particionados).
- **delta-write-patterns**: dedup é `Window` + `row_number()` (determinístico), **não** `dropDuplicates`;
  no `whenMatched`, `dh_criacao_registro` é preservado.

## Como o dl-gen usa as skills

- **data-governance-names** é lida em tempo de execução: as seções `## Prompt do sistema` e `## Prompt do pedido`
  são o prompt do LLM, e as seções *How to Decide the Prefix* e *Guardrails* entram nele como regras. Editar o
  `SKILL.md` muda o que o LLM recebe, sem mexer no código.
- Os `scripts/*.scala` são a fonte dos utilitários do projeto Scala gerado (`templates/transformation/scala/static`);
  um teste garante que continuam iguais (o `TransformColumn` do template só acrescenta os casos marcados
  `[framework]`). A versão PySpark segue as mesmas regras.
- As demais skills documentam as regras que os templates aplicam; ao mudar uma, atualize o template (e vice-versa).

## Criar uma skill

1. Crie `skills/<nome>/SKILL.md` com o frontmatter `name` e `description` ("Use when ...") e as seções *Purpose*,
   *Required Behavior* e *Guardrails*, como as demais.
2. No código, leia com `from framework.skills import load_skill` → `load_skill("<nome>").section("<Título>")` ou
   `.reference("<arquivo>")` (um arquivo em `references/`).
3. Registre onde ela é aplicada em `USED_BY` (`skills/__init__.py`) e acrescente a linha na tabela acima.

---
name: sdd-specification
description: "Use when creating, reviewing, or completing an SDD (Software Design Document) for a new table. Guides the user through the SDD template sections, derives field definitions from source DDL using governance naming rules, and ensures all sections are filled before development begins."
---

# SDD Specification

Use this skill whenever the task involves creating a new SDD document for a table, reviewing an existing SDD for completeness, or helping the user provide the information needed to fill each section of the template.

## Purpose

This skill defines the SDD template as the mandatory specification for any new table development. No implementation should begin without a completed SDD.

The SDD is the **source of truth** during development. Types, transformations, field names, enrichments, and rules defined in the SDD must not be altered by inference or optimization during implementation.

## When to Use

- A new table needs to be developed and there is no SDD yet.
- The user provides a DDL, data dictionary, or field list from a source system and wants to generate the SDD.
- An existing SDD needs to be reviewed for completeness or correctness.
- The user asks what information is needed to start a new table specification.

## SDD Template

Every table SDD document must follow this template with all 10 sections. The file must be named `<nome_da_tabela>_sdd_doc.md` and placed in `docs_sdd/`.

### Section 1: Identificacao

| Campo obrigatorio | Descricao |
|---|---|
| Nome da tabela | Nome fisico da tabela de destino. |
| Comentario | Descricao curta do proposito da tabela. |
| Origem dos dados | Sistema de origem, formato (JSON, CSV, Oracle, etc.) e protocolo de entrega. |

### Section 2: Particionamento

Declarar todos os niveis de particao. O numero de niveis varia por tabela (1, 2 ou mais).

| Campo obrigatorio | Descricao |
|---|---|
| Nivel | Numero sequencial do nivel de particao. |
| Campo | Nome do campo de particao (governanca). |
| Tipo | Tipo Spark (StringType). |
| Descricao | Semantica do campo de particao. |

### Section 3: Chave de Merge (Deduplicacao/Upsert)

Declarar os campos que compoem a chave de merge para operacoes Delta MERGE.

Se existir uma strong key composta, declarar a formula de concatenacao e a ordem exata dos campos.

### Section 4: Schema — Campos Principais

Para cada campo, declarar:

| Atributo | Descricao |
|---|---|
| rawField | Nome do campo na origem (campo raw antes do rename). Para campos derivados via substring, usar a notacao `substring(campo_pai_raw, inicio, tamanho)`. Para campos derivados por concatenacao, usar `concat(campo1, campo2, ...)`. Para campos de sistema sem origem, usar `derivado`. Para campos vindos de enrichment, usar `enrichment(nome_tabela)`. |
| stagingField | Nome final do campo seguindo o padrao de governanca (`<mnemonico>_<nome>`). |
| dataType | Tipo Spark: StringType, IntegerType, LongType, DecimalType(p,s), DateType, TimestampType, BooleanType. |
| transformation | `"default"`, `"format"`, ou `null` (sem transformacao). |
| customFormat | Formato para campos DateType/TimestampType com transformation=format (ex: `yyyyMMdd`). |
| Comentario | Descricao de negocio do campo. |

O mapeamento `rawField → stagingField` e essencial para implementar o passo de rename do pipeline: `DataFrameUtils.renameColumns(raw, rawToStagingMap)`. Sem essa informacao, o desenvolvedor nao consegue construir o mapa de rename.

Agrupar os campos por categoria semantica (identificacao, valores, datas, codigos BIT, cartao, EC, sistema, etc.).

### Section 5: Campos Aninhados (NestedField)

Para campos posicionais que contem subcampos extraidos via substring:

| Atributo | Descricao |
|---|---|
| rawField | Notacao de extracao: `substring(campo_pai_raw, inicio, tamanho)` usando o nome raw do campo pai. |
| Campo pai | Nome do campo pai (stagingField). |
| stagingField | Nome do subcampo extraido. |
| inicio | Posicao de inicio da substring (1-based). |
| tamanho | Tamanho da substring. |
| tipo | Tipo Spark do subcampo. |
| Comentario | Descricao do subcampo. |

Declarar o `setParentChildRelationship` ao final.

Se nao houver campos aninhados, declarar: "Nenhum. Todos os campos sao flat."

### Section 6: Regras de Negocio

Documentar todas as regras condicionais, dominios de valores, campos derivados e regras especiais:

- Dominios de valores com significado (ex: `cd_tipo = 1` significa Aprovada).
- Regras condicionais (ex: campo X so e preenchido quando Y = Z).
- Campos derivados (ex: id composto por concat de outros campos).
- Regras de seguranca (tokenizacao, criptografia, hash).
- Regex ou logica de extracao especial.

### Section 7: Enrichments

Para cada enrichment (join com tabela de lookup):

| Atributo | Descricao |
|---|---|
| Dataset | Nome do dataset de origem. |
| Tabela | Nome da tabela de lookup. |
| Colunas retornadas | Campos recuperados do lookup. |
| Aliases | Renomeacao dos campos (se aplicavel). |
| Condicao de join | Campos de join (lookup → df). |
| Tipo de join | left, right ou inner. |
| Status | Ativo ou Inativo. |

Se nao houver enrichments, declarar: "Nenhum enrichment definido."

### Section 8: Joins Inter-tabelas

Para tabelas que fazem join com outras tabelas do dataset:

| Atributo | Descricao |
|---|---|
| Tipo de join | RIGHT, LEFT, INNER. |
| Filtro de particao | Condicao de filtro na tabela de origem. |
| Chaves de join | Campos usados na condicao de join. |
| Colunas removidas | Campos descartados apos o join. |
| Colunas renomeadas | Campos renomeados apos o join. |

Se nao aplicavel, declarar: "Nao aplicavel."

### Section 9: Transformacoes

Documentar o mapeamento de transformacoes por tipo:

- `StringType default` → `trim(upper(col))`
- `IntegerType default` → `col.cast(IntegerType)`
- `LongType default` → `col.cast(LongType)`
- `DecimalType default` → `col.cast(DecimalType)`
- `DateType default` → `to_date(col)`
- `DateType format` → `to_date(col, customFormat)`
- `TimestampType default` → `to_timestamp(normalizeTimestampString(col))`
- `TimestampType format` → `to_timestamp(normalizeTimestampString(col), customFormat)`
- `BooleanType default` → `when(col.isin("s","S","true"), true).when(col.isin("n","N","false"), false)`
- `null` → sem transformacao (valor preservado como recebido)

Listar campos com tratamento especial (casts pos-substring, regex, etc.).

### Section 10: Escrita e Persistencia

| Atributo | Descricao |
|---|---|
| Modo inicial | SaveMode.Overwrite com particionamento. |
| Modo incremental | Delta MERGE com condicoes null-safe (`<=>`). |
| Merge keys | Campos da chave de merge (referencia secao 3). |
| Persist | Estrategia de persist (se MERGE). |
| Manifesto | symlink_format_manifest. |
| Tabela Hive | CREATE EXTERNAL TABLE IF NOT EXISTS. |
| Particoes | ALTER TABLE ADD IF NOT EXISTS PARTITION em lotes de 100. |

## Derivando o SDD a partir de DDL de origem

Quando o usuario fornece um DDL da base de origem (Oracle, PostgreSQL, etc.), seguir este processo:

### Passo 1: Extrair campos do DDL

Identificar cada coluna do DDL com seu nome original (este sera o `rawField`), tipo de dado e comentario (se disponivel). O nome original deve ser preservado na coluna `rawField` do schema final para permitir o mapeamento de rename.

### Passo 2: Aplicar governanca de nomes

Para cada campo de origem, aplicar a skill **data-governance-names**:

1. Identificar a natureza da informacao (codigo, nome, valor, data, etc.).
2. Selecionar o mnemonico correspondente.
3. Construir o nome final no formato `<mnemonico>_<nome_do_campo>`.

Mapeamento de referencia rapida:

| Natureza | Mnemonico | Exemplo |
|---|---|---|
| codigo | `cd` | `cd_tipo_transacao` |
| nome | `nm` | `nm_cliente` |
| descricao | `dc` | `dc_produto` |
| data | `dt` | `dt_movimento` |
| data_hora | `dh` | `dh_criacao_registro` |
| valor | `vl` | `vl_total_transacao` |
| numero | `nu` | `nu_sequencial` |
| quantidade | `qt` | `qt_parcelas` |
| indicador | `in` | `in_ativo` |
| identificador | `id` | `id_pedido` |
| percentual | `pc` | `pc_taxa_juro` |
| sigla | `sg` | `sg_uf` |
| texto | `tx` | `tx_observacao` |

### Passo 3: Mapear tipos de dado

Converter o tipo de dado da origem para o tipo Spark correspondente:

| Tipo Origem (Oracle/SQL) | Tipo Spark | Observacao |
|---|---|---|
| VARCHAR2, CHAR, CLOB | StringType | - |
| NUMBER(p,0) onde p <= 10 | IntegerType | - |
| NUMBER(p,0) onde p > 10 | LongType | - |
| NUMBER(p,s) onde s > 0 | DecimalType(p,s) | Manter precisao e escala originais. |
| DATE (sem horario) | DateType | - |
| DATE (com horario), TIMESTAMP | TimestampType | - |
| FLOAT, BINARY_FLOAT | FloatType | Raro. Preferir DecimalType quando possivel. |
| DOUBLE, BINARY_DOUBLE | DoubleType | Raro. Preferir DecimalType quando possivel. |
| BOOLEAN, CHAR(1) com S/N | BooleanType | Apenas quando confirmado como flag. |

### Passo 4: Definir transformacao

Aplicar a regra de transformacao com base na skill **data-transformation-patterns**:

| Tipo Spark | Transformacao padrao | Quando usar null |
|---|---|---|
| StringType | `"default"` (TRIM+UPPER) | Campos criptografados, hashes, tokens, dados binarios, campos que devem preservar case. |
| IntegerType | `"default"` (cast) | - |
| LongType | `"default"` (cast) | - |
| DecimalType | `"default"` (cast) | - |
| DateType | `"default"` (to_date) ou `"format"` | Usar `"format"` quando o formato nao e ISO (ex: yyyyMMdd). |
| TimestampType | `"default"` (normalizeTimestamp) ou `"format"` | Usar `"format"` quando o formato nao e ISO. |
| BooleanType | `"default"` (S/N → true/false) | - |

### Passo 5: Preencher as secoes restantes

Apos definir o schema (secao 4), solicitar ao usuario as informacoes para as demais secoes:

| Secao | Informacao necessaria | Pode derivar do DDL? |
|---|---|---|
| 1. Identificacao | Nome da tabela, comentario, origem | Parcialmente (nome e comentario do DDL). |
| 2. Particionamento | Campos e niveis de particao | **Nao.** Decisao de arquitetura. |
| 3. Chave de Merge | Campos da chave de deduplicacao | Parcialmente (PK do DDL como ponto de partida). |
| 4. Schema | Campos, tipos, transformacoes | **Sim.** Derivavel do DDL + governanca. |
| 5. Campos Aninhados | Posicoes de substring | **Nao.** Depende de especificacao posicional. |
| 6. Regras de Negocio | Dominios, condicionais, derivacoes | Parcialmente (constraints do DDL). |
| 7. Enrichments | Tabelas de lookup, condicoes de join | **Nao.** Decisao de negocio. |
| 8. Joins Inter-tabelas | Tabelas relacionadas, chaves | **Nao.** Decisao de arquitetura. |
| 9. Transformacoes | Mapeamento de tipos | **Sim.** Derivavel do passo 4. |
| 10. Escrita | Modo, merge keys, persist | Parcialmente (merge keys da secao 3). |

## Informacoes que o usuario deve fornecer

### Minimo obrigatorio para iniciar

1. **DDL da tabela de origem** ou lista de campos com tipos e descricoes.
2. **Nome da tabela de destino** (se diferente da origem).
3. **Formato de entrada** dos dados (JSON, CSV posicional, Oracle, etc.).

### Necessarias para completar o SDD

4. **Campos de particao** — quais campos e em quantos niveis.
5. **Chave de merge** — quais campos identificam um registro unico para deduplicacao.
6. **Campos posicionais** — se existem campos com subcampos extraidos por substring, fornecer as posicoes.
7. **Regras de negocio** — dominios de valores, campos condicionais, formulas de derivacao.
8. **Enrichments** — se a tabela faz join com tabelas de lookup, fornecer tabela, campos de join e colunas retornadas.
9. **Joins inter-tabelas** — se a tabela se relaciona com outras tabelas do pipeline.
10. **Campos sem transformacao** — quais campos devem preservar o valor original (criptografia, hash, tokens).

### Informacoes que podem ser inferidas

- **Nomes de campos** — derivados do DDL via governanca.
- **Tipos Spark** — mapeados do tipo de origem.
- **Transformacoes** — padrao por tipo, exceto campos marcados como null.
- **Secao de escrita** — segue o padrao Delta (merge/overwrite) com merge keys da secao 3.

## Required Behavior

Ao auxiliar o usuario na criacao de um SDD:

1. Se o usuario fornecer um DDL, processar automaticamente os passos 1-4 e gerar a secao 4 (Schema).
2. Identificar quais secoes podem ser preenchidas com a informacao disponivel.
3. Listar explicitamente quais informacoes estao faltando para completar o SDD.
4. Nao inventar informacoes que o usuario nao forneceu (particionamento, enrichments, regras de negocio).
5. Usar a skill **data-governance-names** para toda nomeacao de campos.
6. Usar a skill **data-transformation-patterns** para toda definicao de transformacao.
7. Gerar o documento final no formato do template definido nesta skill.
8. Se nao for possivel completar uma secao, declarar explicitamente: "Informacao pendente: [o que falta]."

## Exemplo de interacao

```
Usuario: Tenho essa DDL de uma tabela Oracle que preciso criar o SDD:
  CREATE TABLE TRANSACAO_PAGAMENTO (
    CD_TRANSACAO    NUMBER(11),
    DT_PAGAMENTO    DATE,
    VL_PAGAMENTO    NUMBER(19,4),
    NM_CLIENTE      VARCHAR2(100),
    NU_CARTAO_CRIPTO VARCHAR2(64)
  );

Assistente: Com base no DDL, consigo gerar as secoes 4 (Schema) e 9 (Transformacoes):

### Schema derivado:
| rawField | stagingField | dataType | transformation | Comentario |
|---|---|---|---|---|
| CD_TRANSACAO | cd_transacao | LongType | default | Codigo da transacao. |
| DT_PAGAMENTO | dt_pagamento | DateType | default | Data do pagamento. |
| VL_PAGAMENTO | vl_pagamento | DecimalType(19,4) | default | Valor do pagamento. |
| NM_CLIENTE | nm_cliente | StringType | default | Nome do cliente. |
| NU_CARTAO_CRIPTO | nu_cartao_cripto | StringType | null | Numero do cartao criptografado. |

Nota: `nu_cartao_cripto` foi marcado com transformation=null
por ser um campo criptografado que deve preservar o valor original.

Para completar o SDD, preciso das seguintes informacoes:
- Secao 1: Nome da tabela de destino e formato de entrada
- Secao 2: Campos e niveis de particionamento
- Secao 3: Campos da chave de merge
- Secao 5: Ha campos posicionais com substring? (Se nao, sera "Nenhum")
- Secao 6: Regras de negocio (dominios, condicionais)
- Secao 7: Enrichments com tabelas de lookup
- Secao 8: Joins com outras tabelas do pipeline
```

## Guardrails

- Nao criar um SDD sem a informacao minima obrigatoria (DDL ou lista de campos).
- Nao inferir particionamento — sempre solicitar ao usuario.
- Nao inferir enrichments — sempre solicitar ao usuario.
- Nao alterar tipos ou transformacoes definidas no SDD durante a implementacao (Principio de Fidelidade).
- Nao adicionar campos, niveis de particao ou regras que nao foram declarados pelo usuario.
- Nao omitir secoes do template — todas as 10 secoes devem estar presentes, mesmo que com "Nao aplicavel".
- Nao gerar nomes de campos sem aplicar o padrao de governanca.
- Campos de seguranca (criptografia, hash, token) devem sempre ter transformation=null.

## Cross-references

- **data-governance-names**: Nomenclatura de campos.
- **data-transformation-patterns**: Padroes de transformacao por tipo.
- **timestamp-handling**: Normalizacao de timestamps de origem.
- **processing-timestamp**: Run-timestamp no driver, coluna de particao de atualizacao e pruning do merge (secoes 2/3/10).
- **delta-write-patterns**: Padroes de escrita Delta (secao 10).
- **hive-table-management**: Gerenciamento de tabela Hive (secao 10).
- **enrichment-joins**: Contrato de enrichments (secao 7).
- **fact-to-fact-joins**: Joins inter-tabelas particionados / FactRightJoin (secao 8).
- **nested-field-extraction**: Extracao de campos posicionais / NestedField (secao 5).
- **catalyst-optimization**: Select unico para transformacoes (secao 9).
- **processor-orchestration**: Fluxo canonico do processor (visao geral da implementacao).
- **project-structure**: Layout do projeto e utilitarios.
- **documento_principal_sdd.md**: Documento principal com convencoes transversais.

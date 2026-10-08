# Skills do agente

O conhecimento que cada etapa do `dl-gen` aplica fica aqui, em Markdown, fora do código. Cada skill é uma pasta com
um `SKILL.md` (frontmatter `name`, `description` e `agent` + o texto) e, se precisar, `references/` com os
documentos de apoio.

| Skill | Etapa (código) | O que faz | Usa LLM |
|---|---|---|---|
| [leitura-de-schema](leitura-de-schema/SKILL.md) | `parsers/schema_reader.py` | Lê campos e tipos de DDL, query, Avro, JSON Schema, StructType, planilha, parquet ou CSV | não |
| [nomenclatura](nomenclatura/SKILL.md) | `agents/naming.py` | Nome na staging e descrição de cada campo, no padrão de nomenclatura | sim (opcional) |
| [ingestao](ingestao/SKILL.md) | `agents/input_gen.py` | Gera o `ingestion.yml` do ingestion-orchestrator | não |
| [transformacao](transformacao/SKILL.md) | `agents/transform_gen.py` | Gera o projeto `<dataset>-transformation` (PySpark ou Scala) | não |
| [sdd](sdd/SKILL.md) | `agents/transform_gen.py` | Gera o SDD da tabela | não |

A skill de **nomenclatura** é lida pelo agente em tempo de execução: as seções `## Prompt do sistema` e
`## Prompt do pedido` do `SKILL.md` são o prompt enviado ao LLM. Para mudar o comportamento, edite o arquivo (sem
mexer no código). As demais descrevem as regras que o código aplica; ao mudar a regra no código, atualize a skill.

Para listar: `dl-gen skills`. No Studio, a barra lateral mostra as skills em "Skills do agente".

## Criar uma skill

1. Crie `skills/<nome>/SKILL.md` com o frontmatter:
   ```markdown
   ---
   name: <nome>
   description: <uma frase: o que ela faz>
   agent: <arquivo do código que a usa>
   ---
   ```
2. No código, leia com `from framework.skills import load_skill` → `load_skill("<nome>").section("<Título>")`
   (o texto de uma seção `## <Título>`) ou `.reference("<arquivo>")` (caminho de um arquivo em `references/`).
3. Acrescente a linha na tabela acima.

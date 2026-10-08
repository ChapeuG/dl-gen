---
name: hive-table-management
description: "Use when creating, evolving, or managing Hive/Athena external tables backed by Delta Lake symlink manifests. Covers CREATE EXTERNAL TABLE DDL, Spark-to-Hive type mapping, column/table comments, schema evolution via ALTER TABLE ADD COLUMNS, and incremental partition registration replacing MSCK REPAIR TABLE."
---

# Hive Table Management for Delta Lake

Use this skill whenever the task involves creating or maintaining Hive/Athena external tables that read from Delta Lake symlink manifests.

## Purpose

This skill defines the canonical patterns for managing Hive metastore tables backed by Delta Lake: DDL generation, type mapping, comments, schema evolution, and partition registration.

## Required Behavior

When creating or managing Hive tables for Delta:

1. Use `CREATE EXTERNAL TABLE IF NOT EXISTS` with `SymlinkTextInputFormat` and `ParquetHiveSerDe`.
2. Point the `LOCATION` to `<delta_path>/_symlink_format_manifest/`.
3. Map Spark types to Hive types using the `sparkToHiveType` function.
4. Truncate comments at 255 characters (Hive/Glue metastore limit).
5. Use `ALTER TABLE ADD COLUMNS` for schema evolution instead of recreating the table.
6. Use `ALTER TABLE ADD IF NOT EXISTS PARTITION` for incremental partition registration.
7. Never use `MSCK REPAIR TABLE` on large tables.

## Spark to Hive Type Mapping

```scala
private def sparkToHiveType(dt: DataType): String = dt match {
  case StringType      => "string"
  case IntegerType     => "int"
  case LongType        => "bigint"
  case DoubleType      => "double"
  case FloatType       => "float"
  case BooleanType     => "boolean"
  case DateType        => "date"
  case TimestampType   => "timestamp"
  case d: DecimalType  => s"decimal(${d.precision},${d.scale})"
  case BinaryType      => "binary"
  case _               => "string"
}
```

## Canonical Patterns

### CREATE EXTERNAL TABLE

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS <table_name> (
    `col1` string COMMENT "description",
    `col2` int,
    `col3` timestamp COMMENT "truncated at 255 chars"
)
COMMENT 'table description'
PARTITIONED BY (`partition_l1` string, `partition_l2` string)
ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'
STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.SymlinkTextInputFormat'
  OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat'
LOCATION '<delta_path>/_symlink_format_manifest/'
```

Key points:
- Column names with dots must be replaced by underscores: `f.name.replace(".", "_")`.
- Column names are wrapped in backticks to handle special characters.
- Non-partition columns go in the main column list; partition columns go in `PARTITIONED BY`.
- `ParquetHiveSerDe` + `SymlinkTextInputFormat` is the required combination for Delta manifest tables.

### Column Comments

```scala
private def getColumnComment(fieldName: String, columnComments: Map[String, String]): String = {
  columnComments.getOrElse(fieldName, "") match {
    case c if c.nonEmpty && c.length <= 255 => s""" COMMENT "$c""""
    case c if c.nonEmpty                    => s""" COMMENT "${c.substring(0, 255)}""""
    case _                                  => ""
  }
}
```

Table comments follow the same 255-character truncation rule but use single quotes.

### Schema Evolution

When the Delta table gains new columns (e.g., model changes), detect and add them:

```scala
val existingCols = spark.catalog.listColumns(tableName).collect().map(_.name).toSet
val newColumns = schemaFields.filter(f => !existingCols.contains(f.name))
newColumns.foreach { field =>
  spark.sql(s"ALTER TABLE $tableName ADD COLUMNS (`${field.name.replace(".", "_")}` ${sparkToHiveType(field.dataType)}${getColumnComment(field.name, columnComments)})")
}
```

### Partition Registration (Replacing MSCK REPAIR TABLE)

**Anti-pattern:** `MSCK REPAIR TABLE` scans ALL existing partitions in S3. On large tables with thousands of partitions, this takes ~1 hour.

**Correct pattern:** Register all partitions from the current batch in a single statement:

```scala
// Generalizado para qualquer numero de niveis de particao (Seq[String])
val partitionValues = df
  .select(partitionFields.head, partitionFields.tail: _*)
  .distinct()
  .collect()

val PARTITION_BATCH_SIZE = 100

partitionValues.grouped(PARTITION_BATCH_SIZE).foreach { batch =>
  val partitionClauses = batch.map { row =>
    val kvPairs = partitionFields.zipWithIndex.map { case (fieldName, idx) =>
      s"$fieldName='${row.getString(idx)}'"
    }.mkString(", ")
    s"PARTITION ($kvPairs)"
  }.mkString("\n    ")

  spark.sql(s"ALTER TABLE $tableName ADD IF NOT EXISTS\n    $partitionClauses")
}
```

This produces a single SQL statement with multiple `PARTITION` clauses:

```sql
ALTER TABLE table_name ADD IF NOT EXISTS
  PARTITION (dt_particao='20240101', dt_atualizacao='20240115')
  PARTITION (dt_particao='20240102', dt_atualizacao='20240115')
  PARTITION (dt_particao='20240103', dt_atualizacao='20240115')
```

- 1 chamada ao metastore ao inves de N.
- O(batch_partitions) ao inves de O(all_partitions) do `MSCK REPAIR TABLE`.

## Review Rules

When reviewing Hive table management code, flag the following as deviations:

- Using `MSCK REPAIR TABLE` instead of incremental `ALTER TABLE ADD PARTITION`.
- Missing `IF NOT EXISTS` in CREATE TABLE or ADD PARTITION statements.
- Missing `SymlinkTextInputFormat` for Delta-backed tables.
- `LOCATION` not pointing to `_symlink_format_manifest/` subdirectory.
- Comments exceeding 255 characters without truncation.
- Column names with dots not replaced by underscores.
- Missing schema evolution check when the table already exists.
- Dropping and recreating the table instead of using `ALTER TABLE ADD COLUMNS`.

## Response Expectations

When answering about Hive table management, present in this order when applicable:

- `DDL type` (CREATE TABLE, ALTER TABLE ADD COLUMNS, ALTER TABLE ADD PARTITION)
- `Storage format` (symlink manifest, parquet, json)
- `Type mapping` applied
- `Comment handling`
- `Schema evolution` approach
- `Partition registration` method
- `Open question` if partition structure or column comments are unknown

## Guardrails

- Do not use `MSCK REPAIR TABLE` on tables with more than a few hundred partitions.
- Do not exceed 255 characters in column or table comments.
- Do not omit the `_symlink_format_manifest/` suffix in LOCATION for Delta tables.
- Do not mix `ParquetHiveSerDe` with non-symlink input formats for Delta tables.
- Do not recreate tables to add columns; use `ALTER TABLE ADD COLUMNS`.
- Preserve existing partition structure when adding new columns.

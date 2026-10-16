"""Entrada dos campos em qualquer formato com nome e tipo: DDL, query, JSON, lista, planilha e arquivo de dados."""

from __future__ import annotations

import json

import pandas as pd
import pytest
from click.testing import CliRunner
from openpyxl import Workbook

from framework.parsers.ddl_parser import parse_ddl_tables
from framework.parsers.schema_reader import NO_TYPE_COMMENT, detect_format, read_schema
from framework.ui import service


def _fields(source, filename: str = "", table: str = "") -> dict:
    schema = parse_ddl_tables(read_schema(source, filename, table))[0]
    return {f["raw_field"]: (f["data_type"], f["nullable"], f["is_pk"], f["comment"]) for f in schema["fields"]} | {
        "@table": schema["table_name"]}


def test_ddl_passes_through():
    ddl = "CREATE TABLE public.t (id int PRIMARY KEY, nome varchar(10));"
    assert detect_format(ddl) == "ddl"
    assert read_schema(ddl) == ddl


def test_query_types_from_cast():
    sql = """-- vendas do dia
    WITH base AS (SELECT * FROM x)
    SELECT v.id::bigint AS id_venda, CAST(v.valor AS decimal(12,2)) valor, v.nome, count(*) total,
           CASE WHEN a = 1 THEN 'S' ELSE 'N' END, CONVERT(varchar(10), v.dt) AS dt_txt, current_date AS hoje
    FROM public.vendas v JOIN base b ON 1 = 1"""
    f = _fields(sql)
    assert f["@table"] == "vendas"
    assert f["id_venda"][0] == "LongType"
    assert f["valor"][0] == "DecimalType(12,2)"
    assert f["nome"] == ("StringType", True, False, NO_TYPE_COMMENT)
    assert f["total"][0] == "LongType"
    assert f["coluna_5"][0] == "StringType"
    assert f["dt_txt"][0] == "StringType"
    assert f["hoje"][0] == "DateType"


def test_view_name_and_star_error():
    f = _fields("create or replace view rel.clientes as select cast(id as int) id, nm::text from c")
    assert f["@table"] == "clientes" and f["id"][0] == "IntegerType" and f["nm"][0] == "StringType"
    with pytest.raises(ValueError, match=r"\*"):
        read_schema("SELECT * FROM t")


def test_avro():
    avro = {"type": "record", "name": "pedido", "doc": "Pedidos", "fields": [
        {"name": "id", "type": "long"},
        {"name": "obs", "type": ["null", "string"], "doc": "Observação"},
        {"name": "valor", "type": {"type": "bytes", "logicalType": "decimal", "precision": 10, "scale": 2}},
        {"name": "ts", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "tags", "type": {"type": "array", "items": "string"}},
    ]}
    f = _fields(json.dumps(avro), "pedido.avsc")
    assert f["@table"] == "pedido"
    assert f["id"][:2] == ("LongType", False)
    assert f["obs"] == ("StringType", True, False, "Observação")
    assert f["valor"][0] == "DecimalType(10,2)"
    assert f["ts"][0] == "TimestampType"
    assert f["tags"][0] == "ArrayType(StringType)"


def test_json_schema_and_struct_type():
    js = {"title": "cliente", "required": ["id"], "properties": {
        "id": {"type": "integer"}, "email": {"type": "string", "maxLength": 120, "description": "E-mail"},
        "nasc": {"type": "string", "format": "date"}, "criado": {"type": ["string", "null"], "format": "date-time"}}}
    f = _fields(json.dumps(js))
    assert f["@table"] == "cliente"
    assert f["id"][:2] == ("LongType", False)
    assert f["email"] == ("StringType", True, False, "E-mail")
    assert (f["nasc"][0], f["criado"][0]) == ("DateType", "TimestampType")

    struct = {"type": "struct", "fields": [
        {"name": "a", "type": "integer", "nullable": False, "metadata": {}},
        {"name": "b", "type": "decimal(10,2)", "nullable": True, "metadata": {"comment": "valor"}}]}
    f = _fields(json.dumps(struct), table="spark")
    assert f["@table"] == "spark" and f["a"][:2] == ("IntegerType", False) and f["b"][3] == "valor"


@pytest.mark.parametrize("text", [
    "Campo;Tipo;Descrição;PK\nid_cliente;INTEGER;Código;S\nnome;VARCHAR(100);Nome do cliente;\n",
    "| campo | tipo | descricao | pk |\n|---|---|---|---|\n| id_cliente | integer | Código | x |\n| nome | varchar | Nome do cliente | |\n",
    "col_name\tdata_type\tcomment\nid_cliente\tint\tCódigo\nnome\tstring\tNome do cliente\n",
    '[{"name": "id_cliente", "type": "int", "description": "Código", "pk": true}, {"name": "nome", "type": "string"}]',
])
def test_field_lists(text):
    f = _fields(text, table="cliente")
    assert f["@table"] == "cliente"
    assert f["id_cliente"][0] == "IntegerType"
    assert f["nome"][0] == "StringType"
    assert f["id_cliente"][3] == "Código"


def test_plain_list_needs_known_types():
    f = _fields("id      bigint     chave\nvl_total   decimal(10, 2)\ncriado  timestamp with time zone\n")
    assert (f["id"][0], f["vl_total"][0], f["criado"][0]) == ("LongType", "DecimalType(10,2)", "TimestampType")
    with pytest.raises(ValueError, match="Formato não reconhecido"):
        read_schema("qualquer frase solta")


def test_spreadsheet_with_free_headers(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["Nome do Campo", "Tipo de Dado", "Descrição do campo", "Obrigatório"])
    ws.append(["cd_loja", "NUMBER(10,0)", "Loja", "sim"])
    ws.append(["nm_loja", "VARCHAR2(50)", None, "não"])
    path = tmp_path / "lojas.xlsx"
    wb.save(path)
    f = _fields(path)
    assert f["@table"] == "lojas"
    assert f["cd_loja"] == ("DecimalType(10,0)", False, False, "Loja")
    assert f["nm_loja"][:2] == ("StringType", True)


def test_data_files(tmp_path):
    df = pd.DataFrame({"id": [1, 2], "valor": [1.5, None], "dt": ["2024-01-01", "2024-02-01"],
                       "ts": ["2024-01-01 10:00:00", "2024-01-01T11:00:00Z"], "ok": [True, False]})
    df.to_parquet(tmp_path / "amostra.parquet")
    df.to_csv(tmp_path / "amostra.csv", index=False)
    f = _fields(tmp_path / "amostra.parquet")
    assert (f["id"][0], f["valor"][0], f["ok"][0]) == ("LongType", "DoubleType", "BooleanType")
    f = _fields(tmp_path / "amostra.csv")
    assert (f["dt"][0], f["ts"][0]) == ("DateType", "TimestampType")
    assert all(v[1] for k, v in f.items() if k != "@table")  # amostra não prova NOT NULL


def test_service_and_cli_accept_any_format(tmp_path):
    query = "SELECT CAST(id AS int) AS id, CAST(criado AS timestamp) AS criado_em FROM loja.cliente"
    form, rows = service.columns_from_ddl(query)
    assert (form["table"], form["physicalName"]) == ("cliente", "loja.cliente")
    assert [(r["name"], r["logicalType"]) for r in rows] == [("id", "integer"), ("criado_em", "timestamp")]

    from framework.cli import main

    path = tmp_path / "cliente.sql"
    path.write_text(query, encoding="utf-8")
    result = CliRunner().invoke(main, ["contrato", "--schema", str(path), "--dataset", "loja",
                                       "--output-dir", str(tmp_path / "contracts")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "contracts" / "loja" / "cliente.odcs.yaml").exists()

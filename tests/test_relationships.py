"""Várias tabelas numa DDL e chaves estrangeiras no contrato (relationships do ODCS)."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from framework.cli import main
from framework.parsers.contract_parser import load_contract
from framework.parsers.ddl_parser import parse_ddl, parse_ddl_tables
from framework.ui import service

DDL = """
-- Tabela: actor
CREATE TABLE actor (
    id          INT          NOT NULL AUTO_INCREMENT,
    nome        VARCHAR(100) NOT NULL,
    data_nasc   DATE,
    PRIMARY KEY (id)
);

CREATE TABLE movies (
    id             INT NOT NULL AUTO_INCREMENT,
    titulo         VARCHAR(150) NOT NULL,
    ano_lancamento YEAR,
    PRIMARY KEY (id)
);

-- Tabela associativa (N:N)
CREATE TABLE actor_movies (
    actor_id   INT NOT NULL,
    movie_id   INT NOT NULL,
    personagem VARCHAR(100),  -- opcional
    PRIMARY KEY (actor_id, movie_id),
    CONSTRAINT fk_actor FOREIGN KEY (actor_id) REFERENCES actor(id) ON DELETE CASCADE,
    CONSTRAINT fk_movie FOREIGN KEY (movie_id) REFERENCES movies(id) ON DELETE CASCADE
);
"""


def _contract(**form):
    return service.contract_from_ddl(DDL, {"dataset": "filmes", "sourceType": "mysql",
                                           "rawPartitionColumn": "dt_ingestao", **form},
                                     [{"environment": "dev", "host": "localhost", "port": 3306,
                                       "database": "filmes", "secretId": "arn:secret"}])


def test_parse_all_tables_with_foreign_keys():
    tables = parse_ddl_tables(DDL)
    assert [t["table_name"] for t in tables] == ["actor", "movies", "actor_movies"]
    am = tables[2]
    assert am["pk_fields"] == ["actor_id", "movie_id"]
    refs = {f["raw_field"]: f.get("references") for f in am["fields"]}
    assert refs == {"actor_id": "actor.id", "movie_id": "movies.id", "personagem": None}
    assert [f["is_fk"] for f in am["fields"]] == [True, True, False]
    assert parse_ddl(DDL)["table_name"] == "actor"  # um DDL só: continua valendo a primeira tabela


def test_inline_and_composite_foreign_keys():
    inline = parse_ddl("CREATE TABLE p (id int, org_id uuid REFERENCES public.organizacao(id));")
    assert {f["raw_field"]: f.get("references") for f in inline["fields"]}["org_id"] == "organizacao.id"
    composite = parse_ddl("CREATE TABLE x (a int, b int, FOREIGN KEY (a, b) REFERENCES y (c, d));")
    assert [f.get("references") for f in composite["fields"]] == ["y.c", "y.d"]


def test_contract_from_ddl_has_relationships():
    contract = _contract()
    assert [t["name"] for t in contract["schema"]] == ["actor", "movies", "actor_movies"]
    am = {p["name"]: p for p in contract["schema"][2]["properties"]}
    assert am["actor_id"]["relationships"] == [{"type": "foreignKey", "to": "actor.id"}]
    assert am["movie_id"]["relationships"] == [{"type": "foreignKey", "to": "movies.id"}]
    assert "relationships" not in am["personagem"]
    movies = {p["name"]: p for p in contract["schema"][1]["properties"]}
    assert movies["ano_lancamento"]["logicalType"] == "integer"  # YEAR do MySQL vira número
    # Sem coluna de data de controle: carga full
    load = {t["name"]: dict((p["property"], p["value"]) for p in t["customProperties"])["loadMode"]
            for t in contract["schema"]}
    assert set(load.values()) == {"full"}

    # Ida e volta pelo Studio: a FK continua na coluna
    text = service.dump_contract(contract)
    cols = {c["name"]: c for c in service.form_from_contract(text, "actor_movies")[2]}
    assert cols["actor_id"]["references"] == "actor.id"


def test_relationship_to_missing_column_is_rejected():
    contract = _contract()
    contract["schema"][2]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "actor.nao_existe"}]
    with pytest.raises(ValueError, match="nao_existe"):
        load_contract(yaml.safe_dump(contract))
    contract["schema"][2]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "semtabela"}]
    with pytest.raises(ValueError, match="tabela.coluna"):
        load_contract(yaml.safe_dump(contract))
    # Tabela fora do contrato: aceita (a relação pode apontar para outro produto de dados)
    contract["schema"][2]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "outro.id"}]
    load_contract(yaml.safe_dump(contract))


def test_cli_contract_and_generate_all_tables(tmp_path):
    ddl = tmp_path / "filmes.sql"
    ddl.write_text(DDL, encoding="utf-8")
    runner = CliRunner()
    contract = tmp_path / "filmes.odcs.yaml"
    r = runner.invoke(main, ["contrato", "--ddl", str(ddl), "--dataset", "filmes", "--source-db", "mysql",
                             "--raw-partition-column", "dt_ingestao", "--host", "localhost", "--database", "filmes",
                             "--secret-id", "arn:secret", "-o", str(contract)])
    assert r.exit_code == 0, r.output
    assert "actor_id → actor.id" in r.output

    out = tmp_path / "out"
    r = runner.invoke(main, ["generate", "--contract", str(contract), "--all-tables", "--output-dir", str(out),
                             "--naming-dir", str(tmp_path / "naming"), "--llm-model", ""])
    assert r.exit_code == 0, r.output
    ymls = sorted(p.name for p in (out / "ingestion-config" / "filmes").iterdir())
    assert ymls == ["actor.ingestion.yml", "actor_movies.ingestion.yml", "movies.ingestion.yml"]
    main_py = (out / "filmes-transformation" / "main.py").read_text(encoding="utf-8")
    for model in ("ActorModel", "MoviesModel", "ActorMoviesModel"):
        assert f"{model}.table_name:" in main_py
    sdd = (out / "filmes-transformation" / "docs_sdd" / "actor_movies_sdd_doc.md").read_text(encoding="utf-8")
    assert "`actor.id`" in sdd and "`movies.id`" in sdd


def test_studio_picks_table_from_multi_table_ddl():
    assert service.ddl_tables(DDL) == ["actor", "movies", "actor_movies"]
    form, rows = service.columns_from_ddl(DDL, "mysql", "actor_movies")
    assert form["table"] == "actor_movies"
    assert [r["references"] for r in rows] == ["actor.id", "movies.id", ""]
    with pytest.raises(ValueError, match="xpto"):
        service.columns_from_ddl(DDL, "mysql", "xpto")

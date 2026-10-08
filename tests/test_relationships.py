"""Várias tabelas numa DDL e chaves estrangeiras no contrato (relationships do ODCS)."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from framework.cli import main
from framework.parsers.contract_parser import check_relationships, load_contract
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


def _contracts(**form):
    return service.contracts_from_ddl(DDL, {"dataset": "filmes", "sourceType": "mysql",
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


def test_one_contract_per_table_with_relationships():
    contracts = _contracts()
    assert [c["schema"][0]["name"] for c in contracts] == ["actor", "movies", "actor_movies"]
    assert [len(c["schema"]) for c in contracts] == [1, 1, 1]
    assert [c["name"] for c in contracts] == ["filmes-actor", "filmes-movies", "filmes-actor_movies"]
    actor, movies, actor_movies = contracts
    am = {p["name"]: p for p in actor_movies["schema"][0]["properties"]}
    assert am["actor_id"]["relationships"] == [{"type": "foreignKey", "to": "actor.id"}]
    assert am["movie_id"]["relationships"] == [{"type": "foreignKey", "to": "movies.id"}]
    assert "relationships" not in am["personagem"]
    mv = {p["name"]: p for p in movies["schema"][0]["properties"]}
    assert mv["ano_lancamento"]["logicalType"] == "integer"  # YEAR do MySQL vira número
    # Sem coluna de data de controle: carga full
    load = [dict((p["property"], p["value"]) for p in c["schema"][0]["customProperties"])["loadMode"]
            for c in contracts]
    assert load == ["full", "full", "full"]

    # Ida e volta pelo Studio: a FK continua na coluna
    cols = {c["name"]: c for c in service.form_from_contract(service.dump_contract(actor_movies))[2]}
    assert cols["actor_id"]["references"] == "actor.id"


def test_relationships_are_checked_across_contracts():
    actor, movies, actor_movies = _contracts()
    check_relationships([actor, movies, actor_movies])
    actor_movies["schema"][0]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "actor.nao_existe"}]
    # Sozinho, o contrato aceita (a tabela actor está em outro arquivo)...
    load_contract(yaml.safe_dump(actor_movies))
    # ...mas junto com os outros contratos a coluna inexistente é recusada
    with pytest.raises(ValueError, match="nao_existe"):
        check_relationships([actor, movies, actor_movies])
    actor_movies["schema"][0]["properties"][0]["relationships"] = [{"type": "foreignKey", "to": "semtabela"}]
    with pytest.raises(ValueError, match="tabela.coluna"):
        load_contract(yaml.safe_dump(actor_movies))


def test_cli_contracts_and_generate_folder(tmp_path):
    ddl = tmp_path / "filmes.sql"
    ddl.write_text(DDL, encoding="utf-8")
    runner = CliRunner()
    r = runner.invoke(main, ["contrato", "--ddl", str(ddl), "--dataset", "filmes", "--source-db", "mysql",
                             "--raw-partition-column", "dt_ingestao", "--host", "localhost", "--database", "filmes",
                             "--secret-id", "arn:secret", "-o", str(tmp_path / "contracts")])
    assert r.exit_code == 0, r.output
    assert "actor_id → actor.id" in r.output
    folder = tmp_path / "contracts" / "filmes"
    assert sorted(p.name for p in folder.iterdir()) == [
        "actor.odcs.yaml", "actor_movies.odcs.yaml", "movies.odcs.yaml"]

    out = tmp_path / "out"
    r = runner.invoke(main, ["generate", "--contract", str(folder), "--output-dir", str(out),
                             "--naming-dir", str(tmp_path / "naming"), "--llm-model", ""])
    assert r.exit_code == 0, r.output
    ymls = sorted(p.name for p in (out / "ingestion-config" / "filmes").iterdir())
    assert ymls == ["actor.ingestion.yml", "actor_movies.ingestion.yml", "movies.ingestion.yml"]
    main_py = (out / "filmes-transformation" / "main.py").read_text(encoding="utf-8")
    for model in ("ActorModel", "MoviesModel", "ActorMoviesModel"):
        assert f"{model}.table_name:" in main_py
    sdd = (out / "filmes-transformation" / "docs_sdd" / "actor_movies_sdd_doc.md").read_text(encoding="utf-8")
    assert "`actor.id`" in sdd and "`movies.id`" in sdd

    # FK quebrada entre arquivos: a pasta é recusada antes de gerar qualquer coisa
    text = (folder / "actor_movies.odcs.yaml").read_text(encoding="utf-8").replace("to: actor.id", "to: actor.xpto")
    (folder / "actor_movies.odcs.yaml").write_text(text, encoding="utf-8")
    r = runner.invoke(main, ["generate", "--contract", str(folder), "--dry-run", "--llm-model", ""])
    assert r.exit_code != 0 and "xpto" in r.output


def test_studio_picks_table_from_multi_table_ddl():
    assert service.ddl_tables(DDL) == ["actor", "movies", "actor_movies"]
    form, rows = service.columns_from_ddl(DDL, "mysql", "actor_movies")
    assert form["table"] == "actor_movies"
    assert [r["references"] for r in rows] == ["actor.id", "movies.id", ""]
    with pytest.raises(ValueError, match="xpto"):
        service.columns_from_ddl(DDL, "mysql", "xpto")

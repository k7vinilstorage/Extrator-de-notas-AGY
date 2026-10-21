import json
import os
import sqlite3
import time

from extrator_agy.faxina import faxinar

ANTIGA = "11111111-1111-1111-1111-111111111111"
NOVA = "22222222-2222-2222-2222-222222222222"


def envelhecer(caminho, horas):
    t = time.time() - horas * 3600
    os.utime(caminho, (t, t))
    return caminho


def criar(caminho, horas=0, conteudo=""):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo)
    return envelhecer(caminho, horas)


def test_tmp(tmp_path):
    velha = envelhecer(_pasta(tmp_path / "extrator-lote-abc"), 3)
    em_uso = envelhecer(_pasta(tmp_path / "extrator-lote-fila"), 3)
    recente = _pasta(tmp_path / "extrator-agy-xyz")
    alheia = envelhecer(_pasta(tmp_path / "outro-programa"), 3)

    assert faxinar(tmp_path, None, {em_uso}) == {"tmp": 1}
    assert not velha.exists()
    assert em_uso.exists() and recente.exists() and alheia.exists()


def _pasta(caminho):
    caminho.mkdir()
    (caminho / "nota.jpg").write_bytes(b"x")
    return caminho


def test_dados_do_agy(tmp_path):
    agy = tmp_path / "agy"
    criar(agy / "conversations" / f"{ANTIGA}.db", 2)
    criar(agy / "annotations" / f"{ANTIGA}.pbtxt", 2)
    criar(agy / "brain" / ANTIGA / "x.md", 2)
    envelhecer(agy / "brain" / ANTIGA, 2)
    criar(agy / "conversations" / f"{NOVA}.db")
    criar(agy / "implicit" / "velho.pb", 2)
    criar(agy / "implicit" / "novo.pb")
    criar(agy / "log" / "cli-velho.log", 8 * 24)
    criar(agy / "log" / "cli-novo.log", 2)
    existe = tmp_path / "extrator-agy-viva"
    existe.mkdir()
    criar(agy / "cache" / "last_conversations.json", 0,
          json.dumps({str(existe): NOVA, str(tmp_path / "extrator-agy-sumiu"): ANTIGA}))
    with sqlite3.connect(agy / "conversation_summaries.db") as db:
        db.execute("CREATE TABLE conversation_summaries (conversation_id text, last_modified_time datetime)")
        db.executemany("INSERT INTO conversation_summaries VALUES (?, ?)", [
            (ANTIGA, "2020-01-01 10:00:00.123+00:00"),
            (NOVA, time.strftime("%Y-%m-%d %H:%M:%S+00:00", time.gmtime())),
        ])

    apagados = faxinar(tmp_path, agy)

    assert apagados == {"tmp": 0, "conversas": 1, "resumos": 1, "ultimas_conversas": 1, "implicit": 1, "logs": 1}
    assert not (agy / "conversations" / f"{ANTIGA}.db").exists()
    assert not (agy / "brain" / ANTIGA).exists()
    assert (agy / "conversations" / f"{NOVA}.db").exists()
    assert [p.name for p in (agy / "implicit").iterdir()] == ["novo.pb"]
    assert [p.name for p in (agy / "log").iterdir()] == ["cli-novo.log"]
    assert json.loads((agy / "cache" / "last_conversations.json").read_text()) == {str(existe): NOVA}
    with sqlite3.connect(agy / "conversation_summaries.db") as db:
        assert db.execute("SELECT conversation_id FROM conversation_summaries").fetchall() == [(NOVA,)]


def test_sem_dados_do_agy_nao_cria_nada(tmp_path):
    agy = tmp_path / "agy"
    assert faxinar(tmp_path, agy)["resumos"] == 0
    assert not agy.exists()

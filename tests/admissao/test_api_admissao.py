import logging
import os
import time

import pytest

os.environ.setdefault("EXTRATOR_API_TOKEN", "segredo-de-teste")
os.environ["EXTRATOR_FAXINA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from extrator_agy import api  # noqa: E402
from extrator_agy.admissao import fluxo  # noqa: E402
from extrator_agy.admissao.documentos import normalizar_documento  # noqa: E402
from extrator_agy.admissao.texto import normalizar_texto  # noqa: E402
from extrator_agy.agy import DICA_LOGIN, ErroAgy  # noqa: E402
from extrator_agy.pdf import PdfInvalido  # noqa: E402
from numeros import cpf  # noqa: E402

AUTH = {"Authorization": "Bearer segredo-de-teste"}
CPF = cpf()
TEXTO = "Maria, auxiliar administrativo, R$ 2.500,00"


@pytest.fixture
def lidos(monkeypatch):
    """Troca a leitura (agy) por uma falsa, guiada pelo conteúdo do arquivo; anota as dicas de tipo."""
    dicas = []

    def ler_arquivo(caminho, nome, config, dica_tipo=None):
        dicas.append(dica_tipo)
        conteudo = caminho.read_bytes()
        if conteudo == b"sem login":
            raise ErroAgy(DICA_LOGIN)
        if conteudo == b"pdf ruim":
            raise PdfInvalido("PDF ilegível")
        if conteudo == b"bug":
            raise ValueError(f"MARIA EXEMPLO {CPF}")  # mensagem com dado pessoal, que não pode ir para o log
        fonte = normalizar_documento({"tipo": "rg", "nome": "Maria Exemplo", "rg": {"cpf": CPF}}) | {"arquivo": nome}
        return {"arquivo": nome, "status": "ok", "avisos": [], "fontes": [fonte]}

    def ler_texto(texto, config):
        return normalizar_texto({"contrato": {"cargo": {"valor": "auxiliar administrativo", "trecho": "auxiliar"}}})

    monkeypatch.setattr(fluxo, "ler_arquivo", ler_arquivo)
    monkeypatch.setattr(fluxo, "ler_texto", ler_texto)
    monkeypatch.setattr(api, "admissoes", {})
    return dicas


@pytest.fixture
def cliente(lidos):
    return TestClient(api.app)


def esperar(cliente, url) -> dict:
    for _ in range(100):
        adm = cliente.get(url, headers=AUTH).json()
        if adm["status"] != "processando":
            return adm
        time.sleep(0.02)
    pytest.fail("admissão não terminou")


def test_exige_token(cliente):
    assert cliente.post("/admissao", data={"texto": TEXTO}).status_code == 401
    assert cliente.get("/admissoes/x").status_code == 401


@pytest.mark.parametrize("dados,arquivos,trecho", [
    ({}, None, "ao menos um arquivo"),
    ({"texto": "   "}, None, "ao menos um arquivo"),
    ({"tipos": "[rg"}, [("arquivos", ("a.jpg", b"x"))], "JSON"),
    ({"tipos": '["rg", null]'}, [("arquivos", ("a.jpg", b"x"))], "um item por arquivo"),
    ({"tipos": '["passaporte"]'}, [("arquivos", ("a.jpg", b"x"))], "desconhecidos"),
])
def test_requisicao_invalida(cliente, dados, arquivos, trecho):
    for rota in ("/admissao", "/admissoes"):
        r = cliente.post(rota, data=dados, files=arquivos, headers=AUTH)
        assert r.status_code == 400 and trecho in r.json()["detail"]


def test_limites(cliente, monkeypatch):
    r = cliente.post("/admissao", data={"texto": "x" * 10_001}, headers=AUTH)
    assert r.status_code == 413
    monkeypatch.setattr(api, "MAX_ARQUIVOS_ADMISSAO", 1)
    r = cliente.post("/admissao", files=[("arquivos", ("a.jpg", b"x")), ("arquivos", ("b.jpg", b"x"))], headers=AUTH)
    assert r.status_code == 413
    r = cliente.post("/admissao", files=[("arquivos", ("a.txt", b"x"))], headers=AUTH)
    assert r.status_code == 415


def test_sincrona(cliente, lidos):
    r = cliente.post("/admissao", data={"texto": TEXTO, "tipos": '["rg", null]'}, headers=AUTH,
                     files=[("arquivos", ("rg.jpg", b"x")), ("arquivos", ("ruim.pdf", b"pdf ruim"))])
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["status"] == "concluido" and corpo["resultado"] == "alerta"
    assert corpo["ficha"]["funcionario"]["cpf"] == CPF
    assert corpo["ficha"]["contrato"]["cargo"] == "AUXILIAR ADMINISTRATIVO"
    assert [(d["arquivo"], d["status"]) for d in corpo["documentos"]] == [
        ("rg.jpg", "ok"), ("ruim.pdf", "erro"), ("texto", "ok")]
    assert corpo["documentos"][1]["erro"] == "PDF ilegível"
    assert sorted(lidos, key=str) == [None, "rg"]


def test_so_texto(cliente):
    r = cliente.post("/admissao", data={"texto": TEXTO}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["documentos"] == [{"arquivo": "texto", "status": "ok"}]


def test_sincrona_sem_login(cliente):
    r = cliente.post("/admissao", files=[("arquivos", ("rg.jpg", b"sem login"))], headers=AUTH)
    assert r.status_code == 503 and "docker compose run" in r.json()["detail"]


def test_assincrona(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH,
                     files=[("arquivos", ("rg.jpg", b"x")), ("arquivos", ("ruim.pdf", b"pdf ruim"))])
    assert r.status_code == 202
    assert r.json()["total"] == 3
    id_ = r.json()["id"]
    adm = esperar(cliente, r.json()["url"])
    assert adm["status"] == "concluido" and adm["concluidos"] == 3
    assert adm["ficha"]["funcionario"]["cpf"] == CPF
    assert {d["arquivo"]: d["status"] for d in adm["documentos"]} == {"rg.jpg": "ok", "ruim.pdf": "erro", "texto": "ok"}
    assert not any(k.startswith("_") for k in adm) and "concluido_em" not in adm
    assert not api.admissoes[id_]["_dir"].exists()
    assert api.admissoes[id_]["_dir"] not in api.pastas_em_uso


def test_assincrona_sem_login(cliente):
    r = cliente.post("/admissoes", files=[("arquivos", ("rg.jpg", b"sem login"))], headers=AUTH)
    adm = esperar(cliente, r.json()["url"])
    assert adm["status"] == "erro" and "falha no agy" in adm["erro"]
    assert "ficha" not in adm


def test_apagar(cliente):
    url = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()["url"]
    esperar(cliente, url)
    assert cliente.delete(url, headers=AUTH).status_code == 204
    assert cliente.get(url, headers=AUTH).status_code == 404
    assert cliente.delete(url, headers=AUTH).status_code == 404


def test_expira(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    esperar(cliente, r["url"])
    api.admissoes[r["id"]]["concluido_em"] -= api.ADMISSAO_TTL_S + 1
    assert cliente.get(r["url"], headers=AUTH).status_code == 404


def test_log_sem_dado_pessoal(cliente, caplog):
    caplog.set_level(logging.INFO)
    r = cliente.post("/admissoes", files=[("arquivos", ("rg maria.jpg", b"bug"))], headers=AUTH)
    adm = esperar(cliente, r.json()["url"])
    assert adm["documentos"][0]["erro"] == "erro interno"
    assert "ValueError" in caplog.text
    for dado in ("MARIA", CPF, "maria.jpg"):
        assert dado not in caplog.text

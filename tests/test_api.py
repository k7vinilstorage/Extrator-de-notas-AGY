import os
import time

import pytest

os.environ.setdefault("EXTRATOR_API_TOKEN", "segredo-de-teste")

from fastapi.testclient import TestClient  # noqa: E402

from extrator_agy import api  # noqa: E402
from extrator_agy.agy import ErroAgy  # noqa: E402
from extrator_agy.extracao import Resultado  # noqa: E402
from extrator_agy.pdf import PdfInvalido  # noqa: E402

AUTH = {"Authorization": "Bearer segredo-de-teste"}
NOTA = {"cpf_cnpj": "04.140.144/0001-02", "razao_social": "POSTO Z1 LTDA", "valor_total": 100.0}


@pytest.fixture
def cliente(monkeypatch):
    def falso(caminho, config):
        if caminho.read_bytes() == b"falha":
            raise ErroAgy("sem login")
        if caminho.read_bytes() == b"pdf ruim":
            raise PdfInvalido("PDF ilegível")
        return Resultado(NOTA, [], "QR")

    monkeypatch.setattr(api, "processar", falso)
    return TestClient(api.app)


def test_saude_sem_token(cliente):
    assert cliente.get("/saude").json()["status"] == "ok"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer errado"}])
def test_exige_token(cliente, headers):
    r = cliente.post("/extrair", files={"arquivo": ("a.jpg", b"x")}, headers=headers)
    assert r.status_code == 401


def test_extrair(cliente):
    r = cliente.post("/extrair", files={"arquivo": ("cupom.jpg", b"x")}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"arquivo": "cupom.jpg", "status": "ok", "nota": NOTA, "problemas": [], "origem_chave": "QR"}


def test_extrair_formato_invalido(cliente):
    r = cliente.post("/extrair", files={"arquivo": ("nota.txt", b"x")}, headers=AUTH)
    assert r.status_code == 415


def test_extrair_falha_agy(cliente):
    r = cliente.post("/extrair", files={"arquivo": ("cupom.jpg", b"falha")}, headers=AUTH)
    assert r.status_code == 502
    assert "sem login" in r.json()["detail"]


def test_extrair_pdf_invalido(cliente):
    r = cliente.post("/extrair", files={"arquivo": ("nota.pdf", b"pdf ruim")}, headers=AUTH)
    assert r.status_code == 422
    assert r.json()["detail"] == "nota.pdf: PDF ilegível"


def test_lote(cliente):
    arquivos = [("arquivos", ("a.jpg", b"x")), ("arquivos", ("b.png", b"falha"))]
    r = cliente.post("/lotes", files=arquivos, headers=AUTH)
    assert r.status_code == 202
    url = r.json()["url"]

    for _ in range(50):
        lote = cliente.get(url, headers=AUTH).json()
        if lote["status"] == "concluido":
            break
        time.sleep(0.05)
    assert lote["concluidos"] == 2
    a, b = lote["resultados"]
    assert (a["arquivo"], a["status"], a["nota"]) == ("a.jpg", "ok", NOTA)
    assert (b["arquivo"], b["status"]) == ("b.png", "erro")
    assert "_dir" not in lote


def test_lote_inexistente(cliente):
    assert cliente.get("/lotes/nao-existe", headers=AUTH).status_code == 404

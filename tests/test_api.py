import os
import time

import pytest

os.environ.setdefault("EXTRATOR_API_TOKEN", "segredo-de-teste")
# A faxina de verdade apagaria o histórico do agy de quem roda os testes.
os.environ["EXTRATOR_FAXINA"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from extrator_agy import api  # noqa: E402
from extrator_agy.agy import DICA_LOGIN, ErroAgy  # noqa: E402
from extrator_agy.extracao import Resultado  # noqa: E402
from extrator_agy.pdf import PdfInvalido  # noqa: E402

AUTH = {"Authorization": "Bearer segredo-de-teste"}
NOTA = {"cpf_cnpj": "04.140.144/0001-02", "razao_social": "POSTO Z1 LTDA", "valor_total": 100.0}
LIMITES = {"semanal": {"restante_pct": 44.7, "renova_em": "2026-10-25T20:49:04-03:00"},
           "cinco_horas": {"restante_pct": 91.5, "renova_em": "2026-10-21T19:01:14-03:00"}}


@pytest.fixture
def cliente(monkeypatch):
    def falso(caminho, config):
        if caminho.read_bytes() == b"falha":
            raise ErroAgy("sem login")
        if caminho.read_bytes() == b"pdf ruim":
            raise PdfInvalido("PDF ilegível")
        return Resultado(NOTA, [], "QR")

    monkeypatch.setattr(api, "processar", falso)
    monkeypatch.setattr(api, "faxinar", lambda *a: pytest.fail("faxina rodou com EXTRATOR_FAXINA=0"))
    monkeypatch.setattr(api, "limites", {"dados": None, "em": 0.0, "consulta": None})
    return TestClient(api.app)


@pytest.fixture
def faxinas(monkeypatch):
    """Liga a faxina, trocando a de verdade por uma que só anota as chamadas."""
    chamadas = []
    monkeypatch.setattr(api, "FAXINA", True)
    monkeypatch.setattr(api, "ultima_faxina", 0.0)
    monkeypatch.setattr(api, "faxinar", lambda tmp, dados_agy, em_uso: chamadas.append(em_uso) or {})
    return chamadas


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


def test_faxina_no_maximo_uma_vez_por_intervalo(cliente, faxinas):
    for _ in range(2):
        cliente.post("/lotes", files=[("arquivos", ("a.jpg", b"x"))], headers=AUTH)
    for _ in range(50):
        if faxinas:
            break
        time.sleep(0.01)
    assert len(faxinas) == 1


def test_limites(cliente, monkeypatch):
    consultas = []
    monkeypatch.setattr(api, "consultar_limites", lambda: consultas.append(1) or LIMITES)
    r = cliente.get("/limites", headers=AUTH)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["modelo"] == api.CONFIG.modelo
    assert corpo["semanal"] == LIMITES["semanal"] and corpo["cinco_horas"] == LIMITES["cinco_horas"]
    assert "consultado_em" in corpo
    # Dentro de LIMITES_CACHE_S a resposta sai do cache.
    assert cliente.get("/limites", headers=AUTH).json() == corpo
    assert len(consultas) == 1


def test_limites_resposta_antiga_enquanto_atualiza(cliente, monkeypatch):
    api.limites.update(dados=LIMITES, em=time.time() - api.LIMITES_CACHE_S - 1)
    monkeypatch.setattr(api, "consultar_limites", lambda: (_ for _ in ()).throw(ErroAgy("UNAVAILABLE (code 503)")))
    r = cliente.get("/limites", headers=AUTH)
    assert r.status_code == 200 and r.json()["semanal"] == LIMITES["semanal"]


@pytest.mark.parametrize("erro,codigo", [(ErroAgy("UNAVAILABLE (code 503)"), 502), (ErroAgy(DICA_LOGIN), 503)])
def test_limites_sem_resposta_recente(cliente, monkeypatch, erro, codigo):
    monkeypatch.setattr(api, "consultar_limites", lambda: (_ for _ in ()).throw(erro))
    r = cliente.get("/limites", headers=AUTH)
    assert r.status_code == codigo
    assert "falha ao consultar a cota" in r.json()["detail"]


def test_lote_inexistente(cliente):
    assert cliente.get("/lotes/nao-existe", headers=AUTH).status_code == 404

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

    def ler_arquivo(caminho, nome, config, dica_tipo=None, conferir=None):
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


def test_docx_entra_como_texto(cliente, monkeypatch):
    import zipfile, io
    textos = []
    monkeypatch.setattr(fluxo, "ler_texto", lambda texto, config: textos.append(texto) or normalizar_texto({}))
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:p><w:r><w:t>Ag: 1234 Cc: 5678-9</w:t></w:r></w:p>")
    r = cliente.post("/admissao", data={"texto": "cargo SDR"}, headers=AUTH,
                     files=[("arquivos", ("rg.jpg", b"x")), ("arquivos", ("conta.docx", docx.getvalue()))])
    assert r.status_code == 200
    assert textos == ['cargo SDR\n\n--- conteúdo do arquivo "conta.docx" ---\nAg: 1234 Cc: 5678-9']
    assert r.json()["documentos"][-1] == {"arquivo": "texto", "status": "ok", "inclui": ["conta.docx"]}
    assert [d["arquivo"] for d in r.json()["documentos"]] == ["rg.jpg", "texto"]


def test_docx_invalido(cliente):
    r = cliente.post("/admissao", files=[("arquivos", ("conta.docx", b"nao e zip"))], headers=AUTH)
    assert r.status_code == 422 and "conta.docx" in r.json()["detail"]


def test_so_docx_vazio(cliente):
    import zipfile, io
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:p></w:p>")
    r = cliente.post("/admissoes", files=[("arquivos", ("vazio.docx", docx.getvalue()))], headers=AUTH)
    assert r.status_code == 400


def test_docx_nao_vale_nas_notas(cliente):
    r = cliente.post("/extrair", files={"arquivo": ("nota.docx", b"x")}, headers=AUTH)
    assert r.status_code == 415


# --- complemento: arquivos e texto acrescentados depois -------------------------------

def test_complemento(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    esperar(cliente, r["url"])
    c = cliente.post(f"{r['url']}/complemento", files=[("arquivos", ("rg.jpg", b"x"))], headers=AUTH)
    assert c.status_code == 202
    assert c.json() == {"id": r["id"], "total": 2, "complemento": 1, "url": r["url"]}
    adm = esperar(cliente, r["url"])
    assert adm["status"] == "concluido" and adm["complementos"] == 1 and adm["concluidos"] == 2
    assert [(d["arquivo"], d.get("complemento")) for d in adm["documentos"]] == [
        ("texto", None), ("rg.jpg (complemento 1)", 1)]
    assert adm["ficha"]["funcionario"]["cpf"] == CPF, "o RG do complemento entrou na ficha"
    assert adm["origens"]["funcionario.cpf"][0]["complemento"] == 1
    assert adm["ficha"]["contrato"]["cargo"] == "AUXILIAR ADMINISTRATIVO", "o texto de antes continua"
    interno = api.admissoes[r["id"]]
    assert not interno["_dir"].exists() and interno["_dir"] not in api.pastas_em_uso
    assert all(lido.get("_caminho") is None for lido in interno["_resultados"]), "o arquivo foi apagado"
    assert not any(k.startswith("_") for k in adm)


def test_complemento_recusado(cliente, monkeypatch):
    assert cliente.post("/admissoes/nao-existe/complemento", data={"texto": TEXTO}, headers=AUTH).status_code == 404
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    url = f"{r['url']}/complemento"
    esperar(cliente, r["url"])
    assert cliente.post(url, data={}, headers=AUTH).status_code == 400

    api.admissoes[r["id"]]["status"] = "processando"
    lendo = cliente.post(url, data={"texto": "cargo SDR"}, headers=AUTH)
    assert lendo.status_code == 409 and "ainda está sendo lida" in lendo.json()["detail"]
    api.admissoes[r["id"]]["status"] = "concluido"

    falha = cliente.post(url, files=[("arquivos", ("a.txt", b"x"))], headers=AUTH)
    assert falha.status_code == 415
    adm = cliente.get(r["url"], headers=AUTH).json()
    assert (adm["status"], adm["complementos"]) == ("concluido", 0), "o envio recusado não estraga a ficha"
    assert "concluido_em" in api.admissoes[r["id"]], "e ela volta a expirar"

    monkeypatch.setattr(api, "MAX_COMPLEMENTOS", 1)
    assert cliente.post(url, data={"texto": "cargo SDR"}, headers=AUTH).status_code == 202
    esperar(cliente, r["url"])
    limite = cliente.post(url, data={"texto": "cargo SDR"}, headers=AUTH)
    assert limite.status_code == 409 and "no máximo 1" in limite.json()["detail"]


def test_complemento_sem_login_volta_a_ficha_de_antes(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, files=[("arquivos", ("rg.jpg", b"x"))], headers=AUTH).json()
    antes = esperar(cliente, r["url"])
    cliente.post(f"{r['url']}/complemento", files=[("arquivos", ("cnh.jpg", b"sem login"))], headers=AUTH)
    depois = esperar(cliente, r["url"])
    assert depois["status"] == "concluido" and depois["complementos"] == 0
    assert depois["ficha"] == antes["ficha"] and depois["documentos"] == antes["documentos"]
    assert any(a["mensagem"].startswith("o complemento 1 não foi lido") for a in depois["alertas"])
    de_novo = cliente.post(f"{r['url']}/complemento", data={"texto": "cargo SDR"}, headers=AUTH)
    assert de_novo.status_code == 202 and de_novo.json()["complemento"] == 1


def test_complemento_apagado_enquanto_le(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    esperar(cliente, r["url"])
    assert cliente.post(f"{r['url']}/complemento", data={"texto": "cargo SDR"}, headers=AUTH).status_code == 202
    assert cliente.delete(r["url"], headers=AUTH).status_code == 204
    assert cliente.get(r["url"], headers=AUTH).status_code == 404


def test_complemento_so_com_campos_volta_pronto_e_sem_agy(cliente, lidos, monkeypatch):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, files=[("arquivos", ("rg.jpg", b"x"))], headers=AUTH).json()
    antes = esperar(cliente, r["url"])
    assert any(a["campo"] == "funcionario.estado_civil" for a in antes["alertas"])
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda *a, **k: pytest.fail("chamou o agy"))
    monkeypatch.setattr(fluxo, "ler_texto", lambda *a, **k: pytest.fail("chamou o agy"))
    monkeypatch.setattr(api, "MAX_COMPLEMENTOS", 0)  # só campos não conta no limite

    url = f"{r['url']}/complemento"
    c = cliente.post(url, data={"campos": '{"funcionario.estado_civil": "casado", "contrato.salario": "2.800,00"}'},
                     headers=AUTH)
    assert c.status_code == 202 and c.json() == {"id": r["id"], "total": 2, "complemento": None, "url": r["url"]}
    adm = cliente.get(r["url"], headers=AUTH).json()
    assert adm["status"] == "concluido", "na mesma resposta, sem esperar"
    assert (adm["ficha"]["funcionario"]["estado_civil"], adm["ficha"]["contrato"]["salario"]) == ("casado", 2800.0)
    assert adm["origens"]["funcionario.estado_civil"] == [{"arquivo": "painel", "tipo": "informado"}]
    assert not any(a["campo"] == "funcionario.estado_civil" for a in adm["alertas"])
    assert adm["documentos"] == antes["documentos"] and adm["complementos"] == 0
    assert adm["ficha"]["contrato"]["cargo"] == "AUXILIAR ADMINISTRATIVO", "as leituras de antes continuam"
    assert "concluido_em" in api.admissoes[r["id"]], "e ela volta a expirar"

    cliente.post(url, data={"campos": '{"funcionario.raca_cor": "parda"}'}, headers=AUTH)
    adm = cliente.get(r["url"], headers=AUTH).json()
    assert (adm["ficha"]["funcionario"]["estado_civil"], adm["ficha"]["funcionario"]["raca_cor"]) == ("casado", "parda"), \
        "o informado antes continua valendo"


def test_complemento_com_campo_invalido_nao_mexe_na_ficha(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    antes = esperar(cliente, r["url"])
    url = f"{r['url']}/complemento"
    ruim = cliente.post(url, data={"campos": '{"funcionario.cpf": "11111111111"}'}, headers=AUTH)
    assert ruim.status_code == 400 and "funcionario.cpf" in ruim.json()["detail"]
    assert cliente.post(url, data={"campos": '{"funcionario.cpf": ""}'}, headers=AUTH).status_code == 400, \
        "só campo vazio é o mesmo que não mandar nada"
    depois = cliente.get(r["url"], headers=AUTH).json()
    assert depois == antes
    api.admissoes[r["id"]]["status"] = "processando"
    lendo = cliente.post(url, data={"campos": '{"funcionario.raca_cor": "parda"}'}, headers=AUTH)
    assert lendo.status_code == 409


def test_campos_junto_com_arquivo_e_complemento_que_falha_os_desfaz(cliente):
    r = cliente.post("/admissoes", data={"texto": TEXTO}, headers=AUTH).json()
    esperar(cliente, r["url"])
    url = f"{r['url']}/complemento"
    c = cliente.post(url, data={"campos": '{"funcionario.raca_cor": "parda"}'},
                     files=[("arquivos", ("rg.jpg", b"x"))], headers=AUTH)
    assert c.status_code == 202 and c.json()["complemento"] == 1
    adm = esperar(cliente, r["url"])
    assert adm["ficha"]["funcionario"]["raca_cor"] == "parda" and adm["ficha"]["funcionario"]["cpf"] == CPF

    cliente.post(url, data={"campos": '{"funcionario.raca_cor": "branca"}'},
                 files=[("arquivos", ("cnh.jpg", b"sem login"))], headers=AUTH)
    depois = esperar(cliente, r["url"])
    assert depois["ficha"]["funcionario"]["raca_cor"] == "parda", "o complemento que não entrou leva os campos junto"
    assert api.admissoes[r["id"]]["_informados"] == {"funcionario.raca_cor": "parda"}

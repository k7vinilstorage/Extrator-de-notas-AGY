from extrator_agy.admissao import fluxo
from extrator_agy.admissao.documentos import normalizar_documento
from extrator_agy.agy import DICA_LOGIN, ErroAgy
from extrator_agy.extracao import Config
from numeros import cpf

CPF = cpf()


def item(nome, data):
    fonte = normalizar_documento({"tipo": "rg" if "rg" in nome else "cpf", "nome": "Maria Exemplo da Silva",
                                  "rg" if "rg" in nome else "cpf": {"cpf": CPF, "data_nascimento": data}})
    return {"arquivo": nome, "status": "ok", "avisos": [], "fontes": [fonte | {"arquivo": nome}],
            "_caminho": f"/tmp/{nome}", "_dica": None}


def test_releitura_resolve_divergencia(monkeypatch):
    pedidos = []

    def reler(caminho, nome, config, dica, conferir):
        pedidos.append((nome, conferir))
        return item(nome, "05/03/1990")

    monkeypatch.setattr(fluxo, "ler_arquivo", reler)
    r = fluxo.concluir([item("rg.jpg", "05/03/1993"), item("cpf.jpg", "05/03/1990")], config=Config())
    assert r["ficha"]["funcionario"]["data_nascimento"] == "1990-03-05"
    assert not any(a["tipo"] == "divergente" for a in r["alertas"])
    assert sorted(pedidos) == [("cpf.jpg", ["data_nascimento (CPF)"]), ("rg.jpg", ["data_nascimento (RG)"])]
    assert "_reler" not in r


def test_sem_config_nao_rele(monkeypatch):
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda *a: (_ for _ in ()).throw(AssertionError("releu")))
    r = fluxo.concluir([item("rg.jpg", "05/03/1993"), item("cpf.jpg", "05/03/1990")])
    assert any(a["tipo"] == "divergente" for a in r["alertas"])


def test_falha_na_releitura_mantem_a_leitura_anterior(monkeypatch):
    monkeypatch.setattr(fluxo, "ler_arquivo", lambda *a: (_ for _ in ()).throw(ErroAgy(DICA_LOGIN)))
    r = fluxo.concluir([item("rg.jpg", "05/03/1993"), item("cpf.jpg", "05/03/1990")], config=Config())
    assert any(a["campo"] == "funcionario.data_nascimento" and a["tipo"] == "divergente" for a in r["alertas"])


def test_juntar_texto():
    assert fluxo.juntar_texto("cargo SDR", [("conta.docx", "Ag 1234"), ("vazio.docx", "  ")]) == \
        'cargo SDR\n\n--- conteúdo do arquivo "conta.docx" ---\nAg 1234'
    assert fluxo.juntar_texto(None, []) is None

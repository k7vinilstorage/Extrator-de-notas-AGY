from datetime import date, timedelta

from extrator_agy.admissao.documentos import normalizar_documento
from extrator_agy.admissao.ficha import montar
from extrator_agy.admissao.texto import normalizar_texto
from numeros import cpf, pis, titulo

CPF = cpf("123456789")
CPF_FILHO = cpf("987654321")
ADMISSAO = (date.today() + timedelta(days=7)).strftime("%d/%m/%Y")
REFERENCIA = (date.today() - timedelta(days=20)).strftime("%d/%m/%Y")


def doc(tipo: str, nome: str | None, **campos) -> dict:
    return normalizar_documento({"tipo": tipo, "nome": nome, tipo: campos})


def arq(nome: str, *fontes: dict) -> dict:
    for f in fontes:
        f["arquivo"] = nome
    return {"arquivo": nome, "status": "ok", "avisos": [], "fontes": list(fontes)}


def citado(valor):
    return {"valor": valor, "trecho": valor}


def texto(funcionario: dict | None = None, contrato: dict | None = None, dependentes: list | None = None) -> dict:
    base = {"data_admissao": ADMISSAO, "cargo": "auxiliar administrativo", "salario": "R$ 2.500,00",
            "tipo_contrato": "indeterminado", "horario": {"entrada": "8h", "saida": "17h"}}
    funcionario = {"raca_cor": "parda", "estado_civil": "solteira"} | (funcionario or {})
    contrato = base | (contrato or {})

    def citar(d):
        return {k: citar(v) if isinstance(v, dict) else citado(v) for k, v in d.items()}
    return normalizar_texto({"funcionario": citar(funcionario), "contrato": citar(contrato),
                             "dependentes": dependentes or []})


def documentos_completos() -> list[dict]:
    return [
        arq("ctps.pdf", doc("ctps_digital", "Maria Exemplo da Silva", cpf=CPF, data_nascimento="05/03/1990",
                            sexo="Feminino", nacionalidade="Brasileira", pis=pis())),
        arq("rg.jpg", doc("rg", "MARIA EXEMPLO DA SILVA", numero="12.345.678-9", orgao_emissor="SSP", uf_emissor="SC",
                          data_expedicao="10/01/2008", cpf=CPF, data_nascimento="05/03/1990",
                          nome_mae="Ana Exemplo", naturalidade="Joinville", uf_naturalidade="SC")),
        arq("certidao.jpg", doc("certidao_nascimento", "Maria Exemplo da Silva", data_nascimento="05/03/1990",
                                sexo="F", nome_mae="Ana Exemplo", municipio_nascimento="Joinville", uf_nascimento="SC")),
        arq("titulo.jpg", doc("titulo_eleitor", "Maria Exemplo da Silva", numero=titulo(), zona="12", secao="345",
                              uf="SC")),
        arq("luz.pdf", doc("comprovante_residencia", None, titular="Maria Exemplo da Silva", logradouro="Rua A",
                           numero="10", bairro="Centro", municipio="Joinville", uf="SC", cep="89201-000",
                           data_referencia=REFERENCIA)),
        arq("diploma.jpg", doc("comprovante_escolaridade", "Maria Exemplo da Silva", nivel="Ensino Médio",
                               situacao="concluído")),
        arq("filho.jpg", doc("certidao_nascimento", "João Exemplo da Silva", data_nascimento="01/02/2015", sexo="M",
                             nome_mae="Maria Exemplo da Silva")),
        arq("cpf-filho.jpg", doc("cpf", "JOAO EXEMPLO DA SILVA", cpf=CPF_FILHO)),
    ]


def tipos_de_alerta(r: dict) -> dict:
    return {(a["campo"], a["tipo"]) for a in r["alertas"]}


def test_ficha_completa_sem_alertas():
    r = montar(documentos_completos(), texto(dependentes=[
        {"nome": "João", "parentesco": "filho", "irrf": "sim", "salario_familia": "não", "trecho": "o João entra no IR"}]))
    assert r["alertas"] == []
    f = r["ficha"]["funcionario"]
    assert (f["nome"], f["cpf"], f["data_nascimento"], f["sexo"]) == ("MARIA EXEMPLO DA SILVA", CPF, "1990-03-05", "F")
    assert (f["estado_civil"], f["raca_cor"], f["grau_instrucao"]) == ("solteiro", "parda", "medio_completo")
    assert (f["pais_nascimento"], f["municipio_nascimento"], f["uf_nascimento"]) == ("BRASIL", "JOINVILLE", "SC")
    assert f["rg"] == {"numero": "12.345.678-9", "orgao_emissor": "SSP", "uf_emissor": "SC", "data_expedicao": "2008-01-10"}
    assert f["endereco"]["cep"] == "89201-000" and f["cnh"] is None and f["banco"] is None
    assert f["titulo_eleitor"]["numero"] == titulo().replace(" ", "")
    [filho] = r["ficha"]["dependentes"]
    assert (filho["nome"], filho["cpf"], filho["parentesco"], filho["irrf"], filho["salario_familia"]) == \
        ("JOÃO EXEMPLO DA SILVA", CPF_FILHO, "filho", True, False)
    c = r["ficha"]["contrato"]
    assert (c["cargo"], c["salario"], c["horario"]["entrada"]) == ("AUXILIAR ADMINISTRATIVO", 2500.0, "08:00")
    assert c["experiencia"] is None and c["aso"] is None


def test_origens():
    r = montar(documentos_completos(), texto())
    assert r["origens"]["funcionario.cpf"] == [{"arquivo": "ctps.pdf", "tipo": "ctps_digital"},
                                               {"arquivo": "rg.jpg", "tipo": "rg"}]
    assert r["origens"]["contrato.salario"] == [{"arquivo": "texto", "tipo": "texto", "trecho": "R$ 2.500,00"}]
    assert r["origens"]["dependentes[0].parentesco"][0]["deduzido"] is True


def test_resumo_dos_documentos():
    r = montar(documentos_completos() + [{"arquivo": "ruim.pdf", "status": "erro", "erro": "PDF ilegível"}], texto())
    docs = {d["arquivo"]: d for d in r["documentos"]}
    assert docs["rg.jpg"] == {"arquivo": "rg.jpg", "status": "ok", "tipos": ["rg"], "descricoes": [None],
                              "pessoas": ["titular"]}
    assert docs["filho.jpg"]["pessoas"] == docs["cpf-filho.jpg"]["pessoas"] == ["dependente:1"]
    assert docs["ruim.pdf"] == {"arquivo": "ruim.pdf", "status": "erro", "erro": "PDF ilegível"}
    assert any(a["arquivo"] == "ruim.pdf" for a in r["alertas"])


def test_nome_divergente_fica_null_com_os_candidatos():
    # O RG tem o nome de solteira, mas o CPF é o mesmo: é a mesma pessoa.
    arquivos = documentos_completos()
    arquivos[1] = arq("rg.jpg", doc("rg", "Maria Exemplo", cpf=CPF, data_nascimento="05/03/1990"))
    r = montar(arquivos, texto())
    assert r["ficha"]["funcionario"]["nome"] is None
    [alerta] = [a for a in r["alertas"] if a["campo"] == "funcionario.nome"]
    assert alerta["tipo"] == "divergente"
    assert {(c["valor"], c["arquivo"]) for c in alerta["candidatos"]} == {
        ("MARIA EXEMPLO DA SILVA", "ctps.pdf"), ("MARIA EXEMPLO", "rg.jpg"),
        ("MARIA EXEMPLO DA SILVA", "certidao.jpg"), ("MARIA EXEMPLO DA SILVA", "titulo.jpg")}
    assert "rg.jpg" in [d["arquivo"] for d in r["documentos"] if d.get("pessoas") == ["titular"]]


def test_nome_de_casada_explicado_pela_certidao():
    arquivos = documentos_completos()
    arquivos[2] = arq("certidao.jpg", doc("certidao_nascimento", "Maria Exemplo", data_nascimento="05/03/1990",
                                          nome_mae="Ana Exemplo"))
    arquivos.append(arq("casamento.jpg", doc("certidao_casamento", None, conjuge_1="José da Silva",
                                             conjuge_2="Maria Exemplo",
                                             conjuge_2_nome_apos_casamento="Maria Exemplo da Silva")))
    r = montar(arquivos, texto(funcionario={"estado_civil": "casada"}))
    alerta = next(a for a in r["alertas"] if a["campo"] == "funcionario.nome")
    assert "certidão de casamento registra a mudança de nome" in alerta["mensagem"]
    assert r["ficha"]["funcionario"]["estado_civil"] == "casado"
    conjuge = next(d for d in r["ficha"]["dependentes"] if d["parentesco"] == "conjuge")
    assert conjuge["nome"] == "JOSÉ DA SILVA"


def test_texto_e_certidao_divergem_no_estado_civil():
    arquivos = documentos_completos() + [arq("casamento.jpg", doc("certidao_casamento", None, conjuge_1="José da Silva",
                                                                   conjuge_2="Maria Exemplo da Silva"))]
    r = montar(arquivos, texto(funcionario={"estado_civil": "solteira"}))
    assert r["ficha"]["funcionario"]["estado_civil"] is None
    assert ("funcionario.estado_civil", "divergente") in tipos_de_alerta(r)


def test_estado_civil_deduzido_pede_confirmacao():
    r = montar(documentos_completos(), texto(funcionario={"estado_civil": None}))
    assert r["ficha"]["funcionario"]["estado_civil"] == "solteiro"
    assert ("funcionario.estado_civil", "aviso") in tipos_de_alerta(r)


def test_frente_e_verso_se_completam():
    arquivos = [arq("frente.jpg", doc("rg", "Maria Exemplo da Silva", numero="12.345.678-9")),
                arq("verso.jpg", doc("rg", "Maria Exemplo da Silva", data_expedicao="10/01/2008", cpf=CPF))]
    f = montar(arquivos, None)["ficha"]["funcionario"]
    assert (f["rg"]["numero"], f["rg"]["data_expedicao"], f["cpf"]) == ("12.345.678-9", "2008-01-10", CPF)


def test_valor_invalido_vira_alerta_e_nao_entra():
    errado = CPF[:-1] + ("0" if CPF[-1] != "0" else "1")
    r = montar([arq("rg.jpg", doc("rg", "Maria", cpf=errado))], None)
    assert r["ficha"]["funcionario"]["cpf"] is None
    alerta = next(a for a in r["alertas"] if a["campo"] == "funcionario.cpf")
    assert (alerta["tipo"], alerta["valor"], alerta["arquivo"]) == ("invalido", errado, "rg.jpg")


def test_sem_nada_tudo_ausente():
    r = montar([], None)
    ausentes = {a["campo"] for a in r["alertas"] if a["tipo"] == "ausente"}
    assert {"funcionario.cpf", "funcionario.raca_cor", "contrato.salario", "contrato.data_admissao"} <= ausentes
    assert r["ficha"]["dependentes"] == [] and r["ficha"]["outras_informacoes"] == []


def test_dependente_so_no_texto():
    r = montar(documentos_completos(), texto(dependentes=[
        {"nome": "Pedro Souza", "parentesco": "enteado", "irrf": "sim", "salario_familia": None, "trecho": "x"}]))
    pedro = next(d for d in r["ficha"]["dependentes"] if d["nome"] == "PEDRO SOUZA")
    assert pedro["parentesco"] == "enteado"
    assert any(a["mensagem"] == "dependente citado no texto sem documento" for a in r["alertas"])


def test_certidao_de_enteado_citado_no_texto():
    arquivos = documentos_completos() + [arq("pedro.jpg", doc("certidao_nascimento", "Pedro Souza Lima",
                                                              data_nascimento="01/01/2012", nome_mae="Clara Souza"))]
    r = montar(arquivos, texto(dependentes=[
        {"nome": "Pedro", "parentesco": "enteado", "irrf": None, "salario_familia": None, "trecho": "x"}]))
    pedro = next(d for d in r["ficha"]["dependentes"] if d["nome"] == "PEDRO SOUZA LIMA")
    assert (pedro["parentesco"], pedro["data_nascimento"]) == ("enteado", "2012-01-01")


def test_documento_de_outra_pessoa():
    arquivos = documentos_completos() + [arq("vizinho.jpg", doc("rg", "Fulano de Tal", cpf=cpf("111222333")))]
    r = montar(arquivos, texto())
    assert any(a.get("arquivo") == "vizinho.jpg" and "não é o funcionário" in a["mensagem"] for a in r["alertas"])
    assert next(d for d in r["documentos"] if d["arquivo"] == "vizinho.jpg")["pessoas"] == ["nao_identificada"]
    assert r["ficha"]["funcionario"]["cpf"] == CPF


def test_conferencias_de_plausibilidade():
    velho = (date.today() - timedelta(days=200)).strftime("%d/%m/%Y")
    arquivos = documentos_completos()
    arquivos[4] = arq("luz.pdf", doc("comprovante_residencia", None, titular="João Exemplo", cep="89201-000",
                                     uf="SC", logradouro="Rua A", municipio="Joinville", data_referencia=velho))
    r = montar(arquivos, texto(contrato={"tipo_contrato": "experiência", "experiencia": {"dias": "60", "prorrogacao_dias": "45"},
                                         "horario": {"entrada": "22h", "saida": "6h"}}))
    alertas = tipos_de_alerta(r)
    assert ("funcionario.endereco.titular", "aviso") in alertas
    assert ("funcionario.endereco.data_referencia", "aviso") in alertas
    assert ("contrato.experiencia", "invalido") in alertas
    assert ("contrato.horario.saida", "aviso") in alertas


def test_idade_fora_da_faixa():
    arquivos = [arq("rg.jpg", doc("rg", "Maria", data_nascimento="01/01/2020"))]
    assert ("funcionario.data_nascimento", "invalido") in tipos_de_alerta(montar(arquivos, texto()))


def test_nome_do_texto_so_confere():
    r = montar(documentos_completos(), texto(funcionario={"nome": "Maria Silva"}))
    assert r["ficha"]["funcionario"]["nome"] == "MARIA EXEMPLO DA SILVA"
    assert not any(a["campo"] == "funcionario.nome" for a in r["alertas"])
    r = montar(documentos_completos(), texto(funcionario={"nome": "Joana"}))
    assert ("funcionario.nome", "aviso") in tipos_de_alerta(r)


def test_texto_e_documento_divergem_no_endereco():
    r = montar(documentos_completos(), texto(funcionario={"endereco": {"cep": "89202-000"}}))
    assert r["ficha"]["funcionario"]["endereco"]["cep"] is None
    assert ("funcionario.endereco.cep", "divergente") in tipos_de_alerta(r)


def test_ctps_com_nome_abreviado():
    # O caso do primeiro teste real: a CTPS abrevia o nome do meio e todos os outros documentos
    # eram descartados como de "pessoa não identificada".
    arquivos = documentos_completos()
    arquivos[0] = arq("ctps.jpg", doc("ctps_digital", "MARIA E. DA SILVA", pis=pis(), numero="1234567", serie="0050"))
    arquivos[1] = arq("rg.jpg", doc("rg", "Maria Exemplo da Silva", cpf=CPF, data_nascimento="05/03/1990",
                                    nome_mae="Ana Exemplo"))
    r = montar(arquivos, texto())
    assert r["ficha"]["funcionario"]["nome"] == "MARIA EXEMPLO DA SILVA"
    assert not any(a["campo"] == "funcionario.nome" for a in r["alertas"])
    assert not any("não é o funcionário" in a["mensagem"] for a in r["alertas"])
    assert {d["arquivo"]: d["pessoas"] for d in r["documentos"]}["rg.jpg"] == ["titular"]
    assert r["ficha"]["funcionario"]["cpf"] == CPF and r["ficha"]["funcionario"]["pis"] == pis()


def test_contrato_vem_dos_documentos():
    contrato = doc("contrato_trabalho", "Maria Exemplo da Silva", empregador="Empresa Exemplo", cargo="AUXILIAR ADMINISTRATIVO",
                   cbo="4110-05", salario="R$ 2.345,67", data_admissao=ADMISSAO, tipo_contrato="experiência",
                   experiencia_dias="45", prorrogacao_dias="45", horario_entrada="08:00", horario_saida="17:00")
    vt = doc("declaracao_vale_transporte", "Maria Exemplo da Silva", opta="sim")
    r = montar(documentos_completos() + [arq("contrato.pdf", contrato), arq("vt.pdf", vt)],
               texto(contrato={"cargo": None, "salario": None, "tipo_contrato": None, "horario": {}}))
    c = r["ficha"]["contrato"]
    assert (c["empregador"], c["cargo"], c["cbo"], c["salario"]) == ("EMPRESA EXEMPLO", "AUXILIAR ADMINISTRATIVO", "411005", 2345.67)
    assert (c["tipo_contrato"], c["experiencia"]) == ("experiencia", {"dias": 45, "prorrogacao_dias": 45})
    assert (c["horario"]["entrada"], c["horario"]["saida"], c["vale_transporte"]) == ("08:00", "17:00", True)
    assert r["origens"]["contrato.cargo"] == [{"arquivo": "contrato.pdf", "tipo": "contrato_trabalho"}]
    assert not [a for a in r["alertas"] if a["campo"] and a["campo"].startswith("contrato")]


def test_proposta_e_texto_divergem_no_salario():
    proposta = doc("contrato_trabalho", "Maria Exemplo da Silva", salario="R$ 2.345,67")
    r = montar(documentos_completos() + [arq("proposta.pdf", proposta)], texto(contrato={"salario": "R$ 2.500,00"}))
    assert r["ficha"]["contrato"]["salario"] is None
    assert ("contrato.salario", "divergente") in tipos_de_alerta(r)


def test_documento_nao_reconhecido_diz_o_que_e():
    outro = normalizar_documento({"tipo": "outro", "descricao": "comprovante de vacinação", "nome": None})
    r = montar(documentos_completos() + [arq("vacina.jpg", outro)], texto())
    assert any(a["mensagem"] == "documento não reconhecido (comprovante de vacinação); o conteúdo não foi usado"
               for a in r["alertas"])
    assert next(d for d in r["documentos"] if d["arquivo"] == "vacina.jpg")["descricoes"] == ["comprovante de vacinação"]


def test_divergencia_de_digito_pede_releitura():
    arquivos = documentos_completos()
    arquivos[1] = arq("rg.jpg", doc("rg", "MARIA EXEMPLO DA SILVA", cpf=CPF, data_nascimento="05/03/1993",
                                    nome_mae="Ana Exemplo"))
    r = montar(arquivos, texto())
    assert ("funcionario.data_nascimento", "divergente") in tipos_de_alerta(r)
    assert r["_reler"] == {"ctps.pdf": ["data_nascimento (CTPS digital)"], "rg.jpg": ["data_nascimento (RG)"],
                           "certidao.jpg": ["data_nascimento (certidão de nascimento)"]}


def test_nome_divergente_nao_pede_releitura():
    arquivos = documentos_completos()
    arquivos[1] = arq("rg.jpg", doc("rg", "Maria Exemplo", cpf=CPF, data_nascimento="05/03/1990"))
    assert montar(arquivos, texto())["_reler"] == {}


def test_aso_preenche_o_contrato():
    aso = doc("aso", "Maria Exemplo da Silva", tipo_exame="admissional", data_exame="28/10/2026", apto="sim")
    r = montar(documentos_completos() + [arq("aso.jpg", aso)], texto())
    assert r["ficha"]["contrato"]["aso"] == {"data": "2026-10-28", "apto": True}


def test_nome_social_igual_ao_civil_nao_conta():
    r = montar(documentos_completos(), texto(funcionario={"nome_social": "Maria Exemplo da Silva"}))
    assert r["ficha"]["funcionario"]["nome_social"] is None and "funcionario.nome_social" not in r["origens"]
    r = montar(documentos_completos(), texto(funcionario={"nome_social": "Mário Silva"}))
    assert r["ficha"]["funcionario"]["nome_social"] == "MÁRIO SILVA"


def test_nacionalidade_pela_certidao_brasileira():
    arquivos = documentos_completos()
    arquivos[0] = arq("ctps.pdf", doc("ctps_digital", "Maria Exemplo da Silva", cpf=CPF))
    r = montar(arquivos, texto())
    assert r["ficha"]["funcionario"]["nacionalidade"] == "BRASILEIRA"
    assert r["origens"]["funcionario.nacionalidade"][0]["deduzido"] is True

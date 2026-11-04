"""Consolidação das fontes (documentos lidos e texto) numa ficha, com origens e alertas.

Quando duas fontes discordam, o código nunca escolhe: o campo fica null e o
alerta traz os candidatos. A precedência só ordena valores iguais, para que
as origens comecem pela fonte mais confiável.
"""

import re
from datetime import date

from . import regras

ROTULOS = {
    "rg": "RG", "cnh": "CNH", "cpf": "CPF", "ctps_digital": "CTPS digital", "titulo_eleitor": "título de eleitor",
    "comprovante_residencia": "comprovante de residência", "certidao_nascimento": "certidão de nascimento",
    "certidao_casamento": "certidão de casamento", "comprovante_escolaridade": "comprovante de escolaridade",
    "comprovante_pis": "comprovante do PIS", "dados_bancarios": "dados bancários", "texto": "texto",
    "deduzido": "certidão", "contrato_trabalho": "contrato ou proposta de trabalho",
    "declaracao_vale_transporte": "declaração de vale-transporte", "outro": "documento não reconhecido",
    "aso": "ASO",
}

IDENTIDADE = ("ctps_digital", "rg", "cnh", "cpf", "titulo_eleitor")
# Documentos que, entregues na admissão, são do funcionário mesmo em nome de outra pessoa.
DO_TITULAR = ("comprovante_residencia", "dados_bancarios", "comprovante_escolaridade", "comprovante_pis",
              "contrato_trabalho", "declaracao_vale_transporte", "aso")
# Destes, um nome que não é o do funcionário merece aviso (no comprovante de residência, o aviso é outro).
AVISAR_OUTRO_NOME = ("contrato_trabalho", "declaracao_vale_transporte", "comprovante_escolaridade", "aso")


def _de(tipo: str, *campos: str) -> list[tuple[str, str]]:
    return [(tipo, c) for c in campos]


_FILIACAO = ["certidao_nascimento", "rg", "cnh", "titulo_eleitor", "ctps_digital"]

# Caminho na ficha → [(tipo da fonte, campo)], em ordem de precedência.
TITULAR = {
    "funcionario.nome": [(t, "nome") for t in ("ctps_digital", "rg", "cnh", "cpf", "certidao_nascimento", "titulo_eleitor")],
    "funcionario.nome_social": [("texto", "funcionario.nome_social")],
    "funcionario.cpf": [(t, "cpf") for t in ("cpf", "ctps_digital", "rg", "cnh", "certidao_nascimento")]
    + [("texto", "funcionario.cpf")],
    "funcionario.pis": [("comprovante_pis", "pis"), ("ctps_digital", "pis"), ("texto", "funcionario.pis")],
    "funcionario.data_nascimento": [(t, "data_nascimento") for t in
                                    ("certidao_nascimento", "rg", "cnh", "ctps_digital", "cpf", "titulo_eleitor")]
    + [("texto", "funcionario.data_nascimento")],
    "funcionario.sexo": [(t, "sexo") for t in ("certidao_nascimento", "rg", "ctps_digital")] + [("texto", "funcionario.sexo")],
    "funcionario.nome_mae": [(t, "nome_mae") for t in _FILIACAO],
    "funcionario.nome_pai": [(t, "nome_pai") for t in _FILIACAO],
    "funcionario.nacionalidade": [("rg", "nacionalidade"), ("ctps_digital", "nacionalidade"),
                                  ("texto", "funcionario.nacionalidade"), ("deduzido", "nacionalidade")],
    "funcionario.pais_nascimento": [("deduzido", "pais_nascimento"), ("texto", "funcionario.pais_nascimento")],
    "funcionario.municipio_nascimento": [("certidao_nascimento", "municipio_nascimento"), ("rg", "naturalidade"),
                                         ("cnh", "local_nascimento")],
    "funcionario.uf_nascimento": [("certidao_nascimento", "uf_nascimento"), ("rg", "uf_naturalidade"),
                                  ("cnh", "uf_nascimento")],
    "funcionario.estado_civil": [("texto", "funcionario.estado_civil"), ("deduzido", "estado_civil")],
    "funcionario.raca_cor": [("texto", "funcionario.raca_cor")],
    "funcionario.grau_instrucao": [("comprovante_escolaridade", "grau_instrucao"), ("texto", "funcionario.grau_instrucao")],
    "funcionario.deficiencia": [("texto", "funcionario.deficiencia")],
    "funcionario.telefone": [("texto", "funcionario.telefone")],
    "funcionario.email": [("texto", "funcionario.email")],
    "funcionario.rg.numero": [("rg", "numero"), ("cnh", "rg_numero"), ("texto", "funcionario.rg.numero")],
    "funcionario.rg.orgao_emissor": [("rg", "orgao_emissor"), ("cnh", "rg_orgao_emissor")],
    "funcionario.rg.uf_emissor": [("rg", "uf_emissor"), ("cnh", "rg_uf")],
    "funcionario.rg.data_expedicao": [("rg", "data_expedicao")],
    "funcionario.cnh.numero": [("cnh", "numero_registro")],
    **{f"funcionario.cnh.{c}": [("cnh", c)] for c in
       ("categoria", "uf_emissor", "data_emissao", "data_primeira_habilitacao", "validade")},
    **{f"funcionario.ctps.{c}": [("ctps_digital", c)] for c in ("numero", "serie", "uf")},
    **{f"funcionario.titulo_eleitor.{c}": [("titulo_eleitor", c)] for c in
       ("numero", "zona", "secao", "uf", "municipio", "data_emissao")},
    **{f"funcionario.endereco.{c}": [("comprovante_residencia", c), ("texto", f"funcionario.endereco.{c}")] for c in
       ("cep", "logradouro", "numero", "complemento", "bairro", "municipio", "uf")},
    "funcionario.endereco.titular": [("comprovante_residencia", "titular")],
    "funcionario.endereco.data_referencia": [("comprovante_residencia", "data_referencia")],
    **{f"funcionario.banco.{c}": [("dados_bancarios", c), ("texto", f"funcionario.banco.{c}")] for c in
       ("banco", "agencia", "conta", "tipo_conta")},
    "funcionario.banco.pix": [("texto", "funcionario.banco.pix")],
}

CONTRATO = [
    "empregador", "data_admissao", "cargo", "funcao", "cbo", "salario", "tipo_salario", "tipo_contrato",
    "experiencia.dias", "experiencia.prorrogacao_dias", "data_termino",
    "horario.entrada", "horario.saida", "horario.intervalo_inicio", "horario.intervalo_fim",
    "horario.intervalo_minutos", "horario.dias", "escala", "jornada_semanal_horas", "local_trabalho",
    "departamento", "sindicato", "vale_transporte", "beneficios", "aso.data", "aso.apto", "primeiro_emprego",
]
# Campo do contrato → campo do documento de contrato (carta proposta, contrato de trabalho...).
CONTRATO_DOCUMENTO = {
    "empregador": "empregador", "data_admissao": "data_admissao", "cargo": "cargo", "funcao": "funcao", "cbo": "cbo", "salario": "salario",
    "tipo_salario": "tipo_salario", "tipo_contrato": "tipo_contrato", "experiencia.dias": "experiencia_dias",
    "experiencia.prorrogacao_dias": "prorrogacao_dias", "data_termino": "data_termino",
    "horario.entrada": "horario_entrada", "horario.saida": "horario_saida",
    "horario.intervalo_minutos": "intervalo_minutos", "horario.dias": "dias_trabalho", "escala": "escala",
    "jornada_semanal_horas": "jornada_semanal_horas", "local_trabalho": "local_trabalho", "beneficios": "beneficios",
}
TITULAR |= {
    f"contrato.{c}": ([("contrato_trabalho", CONTRATO_DOCUMENTO[c])] if c in CONTRATO_DOCUMENTO else [])
    + ([("declaracao_vale_transporte", "opta")] if c == "vale_transporte" else [])
    + ([("aso", {"aso.data": "data_exame", "aso.apto": "apto"}[c])] if c.startswith("aso.") else [])
    + [("texto", f"contrato.{c}")]
    for c in CONTRATO
}

DEPENDENTE = {
    "nome": [(t, "nome") for t in ("certidao_nascimento", "rg", "cpf", "cnh", "conjuge")],
    "cpf": [(t, "cpf") for t in ("cpf", "rg", "cnh", "certidao_nascimento", "conjuge")],
    "data_nascimento": [(t, "data_nascimento") for t in ("certidao_nascimento", "rg", "cnh", "cpf", "conjuge")],
    "sexo": [("certidao_nascimento", "sexo"), ("rg", "sexo")],
    "parentesco": [("deduzido", "parentesco"), ("texto", "parentesco")],
    "certidao.matricula": [("certidao_nascimento", "matricula")],
    **{f"certidao.{c}": [("certidao_nascimento", c)] for c in ("cartorio", "livro", "folha", "termo", "data_registro")},
    "irrf": [("texto", "irrf")],
    "salario_familia": [("texto", "salario_familia")],
}

ESPERADOS = [
    "funcionario.nome", "funcionario.cpf", "funcionario.data_nascimento", "funcionario.sexo",
    "funcionario.nacionalidade", "funcionario.pais_nascimento", "funcionario.estado_civil",
    "funcionario.raca_cor", "funcionario.grau_instrucao", "funcionario.endereco.cep",
    "funcionario.endereco.logradouro", "funcionario.endereco.municipio", "funcionario.endereco.uf",
    "contrato.data_admissao", "contrato.cargo", "contrato.salario", "contrato.tipo_contrato",
    "contrato.horario.entrada", "contrato.horario.saida",
]
ESPERADOS_DEPENDENTE = ["nome", "data_nascimento", "parentesco"]

# Só nestes um valor deduzido pede confirmação: o país pela certidão brasileira ou o
# parentesco de filho pela certidão de nascimento são seguros.
CONFIRMAR_DEDUZIDO = {"funcionario.estado_civil"}

NOMES = ("nome", "nome_mae", "nome_pai", "titular", "conjuge_1", "conjuge_2")

# Campos em que a divergência entre documentos costuma ser erro de leitura de um dígito ou
# letra: os arquivos envolvidos são relidos uma vez antes de virar alerta.
RELER_SE_DIVERGIR = {
    "funcionario.cpf", "funcionario.pis", "funcionario.data_nascimento", "funcionario.nome_mae",
    "funcionario.nome_pai", "funcionario.rg.numero", "funcionario.rg.data_expedicao",
    "funcionario.titulo_eleitor.numero", "funcionario.endereco.cep", "funcionario.endereco.numero",
    "funcionario.ctps.numero", "funcionario.ctps.serie",
}
RELER_DEPENDENTE = {"cpf", "data_nascimento"}


def _chave(campo: str, valor) -> str:
    """Forma de comparar dois valores do mesmo campo: nomes sem acento e partículas; o resto, só letras e números."""
    if campo.rsplit(".", 1)[-1] in NOMES:
        return regras.chave_nome(valor)
    if isinstance(valor, list):
        return "|".join(sorted(_chave(campo, v) for v in valor))
    return re.sub(r"[^0-9A-Z]", "", regras.sem_acento(str(valor)).upper())


def _mesmo_nome(a: str | None, b: str | None) -> bool:
    return bool(a and b) and regras.chave_nome(a) == regras.chave_nome(b)


def _nomes_equivalentes(nomes: list[str]) -> str | None:
    """O nome mais completo, se todos forem ele mesmo ou abreviações dele; senão None."""
    completo = regras.nome_mais_completo(nomes)
    if all(_mesmo_nome(n, completo) or regras.abreviacao(n, completo) for n in nomes):
        return completo
    return None


def _nome_contido(curto: str | None, completo: str | None) -> bool:
    """"Joao Silva" (do texto) cabe em "JOAO EXEMPLO DA SILVA": mesmo primeiro nome e o resto contido."""
    c, n = regras.chave_nome(curto).split(), regras.chave_nome(completo).split()
    return bool(c and n) and c[0] == n[0] and set(c) <= set(n)


def _ref(fonte: dict, campo: str) -> dict:
    ref = {"arquivo": fonte["arquivo"], "tipo": fonte.get("tipo_original", fonte["tipo"])}
    if fonte["tipo"] == "texto":
        ref["trecho"] = fonte.get("trechos", {}).get(campo)
    if fonte["tipo"] == "deduzido":
        ref["deduzido"] = True
    return ref


def _definir(raiz: dict, caminho: str, valor) -> None:
    *grupos, folha = caminho.split(".")
    for grupo in grupos:
        raiz = raiz.setdefault(grupo, {})
    raiz[folha] = valor


def _valor(raiz: dict | None, caminho: str):
    for parte in caminho.split("."):
        raiz = raiz.get(parte) if isinstance(raiz, dict) else None
    return raiz


def _esvaziar(objeto: dict, raiz: bool = True) -> dict | None:
    """Sub-objetos sem nenhum valor viram null (sem RG, sem CNH...)."""
    for k, v in objeto.items():
        if isinstance(v, dict):
            objeto[k] = _esvaziar(v, raiz=False)
    return objeto if raiz or any(v is not None for v in objeto.values()) else None


class _Montagem:
    """Estado da consolidação: alertas e origens acumulados enquanto os campos são decididos."""

    def __init__(self):
        self.alertas: list[dict] = []
        self.origens: dict[str, list[dict]] = {}
        # Caminho divergente → [(fonte, campo no documento)], para a releitura.
        self.divergencias: dict[str, list[tuple[dict, str]]] = {}

    def alerta(self, tipo: str, campo: str | None, mensagem: str, **extra) -> None:
        self.alertas.append({"campo": campo, "tipo": tipo, "mensagem": mensagem, **extra})

    def decidir(self, caminho: str, mapa: list[tuple[str, str]], fontes: list[dict]):
        candidatos = [(f["campos"][campo], f, campo) for tipo, campo in mapa for f in fontes
                      if f["tipo"] == tipo and f["campos"].get(campo) is not None]
        if not candidatos:
            return None
        valor = candidatos[0][0]
        if caminho.rsplit(".", 1)[-1] in NOMES and len({_chave(caminho, v) for v, _, _ in candidatos}) > 1:
            # "MARIA E. DA SILVA" e "MARIA EXEMPLO DA SILVA" não divergem: um abrevia o outro.
            valor = _nomes_equivalentes([v for v, _, _ in candidatos])
            if valor:
                candidatos = [(valor, f, c) for _, f, c in candidatos]
        if len({_chave(caminho, v) for v, _, _ in candidatos}) > 1:
            self.divergencias[caminho] = [(f, c) for _, f, c in candidatos]
            rotulos = sorted({ROTULOS[f.get("tipo_original", f["tipo"])] for _, f, _ in candidatos})
            self.alerta("divergente", caminho, f"{caminho} difere entre as fontes ({', '.join(rotulos)})",
                        candidatos=[{"valor": v, **_ref(f, c)} for v, f, c in candidatos])
            return None
        self.origens[caminho] = [_ref(f, c) for _, f, c in candidatos]
        if caminho in CONFIRMAR_DEDUZIDO and all(f["tipo"] == "deduzido" for _, f, _ in candidatos):
            self.alerta("aviso", caminho, f"{caminho} deduzido da certidão; confirme com o funcionário")
        return valor

    def campos_com_alerta(self) -> set[str]:
        return {a["campo"] for a in self.alertas if a["campo"]}


def _titular_nome(fontes: list[dict], texto: dict | None) -> str | None:
    """O nome do funcionário: o que mais aparece nos documentos de identidade, contando abreviações.

    Empate fica com o da CTPS (é ela que diz quem está sendo admitido) e, depois, com o mais
    completo. Sem documento de identidade, vale o nome citado no texto.
    """
    nomes = [(f["campos"]["nome"], f["tipo"]) for f in fontes if f["tipo"] in IDENTIDADE and f["campos"].get("nome")]
    if not nomes:
        return (texto or {}).get("campos", {}).get("funcionario.nome")

    def peso(candidato: tuple[str, str]) -> tuple:
        nome, tipo = candidato
        apoio = sum(regras.mesma_pessoa(nome, outro) for outro, _ in nomes)
        return apoio, tipo == "ctps_digital", len(regras.chave_nome(nome))
    return max(nomes, key=peso)[0]


def _identificar(fontes: list[dict], texto: dict | None, m: _Montagem) -> tuple[list[dict], list[dict]]:
    """Separa as fontes do titular e as de cada dependente. Marca em cada fonte a pessoa."""
    titular = _titular_nome(fontes, texto)
    citados = (texto or {}).get("dependentes", [])
    do_titular, pendentes, dependentes = [], [], []

    def novo_dependente(nome: str, parentesco: str | None, fonte: dict) -> dict:
        deduzido = {"arquivo": fonte["arquivo"], "tipo": "deduzido", "tipo_original": fonte["tipo"],
                    "campos": {"parentesco": parentesco}}
        dependente = {"nome": nome, "fontes": [deduzido] if parentesco else []}
        dependentes.append(dependente)
        return dependente

    for f in fontes:
        c = f["campos"]
        if f["tipo"] == "outro":
            descricao = f" ({f['descricao']})" if f.get("descricao") else ""
            m.alerta("aviso", None, f"documento não reconhecido{descricao}; o conteúdo não foi usado", arquivo=f["arquivo"])
        elif f["tipo"] in DO_TITULAR or regras.mesma_pessoa(c.get("nome"), titular):
            do_titular.append(f)
            if f["tipo"] in AVISAR_OUTRO_NOME and c.get("nome") and titular and not regras.mesma_pessoa(c["nome"], titular):
                m.alerta("aviso", None, f"{ROTULOS[f['tipo']]} em nome de outra pessoa", arquivo=f["arquivo"])
        elif f["tipo"] == "certidao_nascimento" and (regras.mesma_pessoa(c.get("nome_mae"), titular)
                                                     or regras.mesma_pessoa(c.get("nome_pai"), titular)):
            novo_dependente(c.get("nome"), "filho", f)["fontes"].append(f)
        elif f["tipo"] == "certidao_casamento":
            _casamento(f, titular, do_titular, novo_dependente, m)
        else:
            pendentes.append(f)

    # Nome diferente (de solteira, por exemplo) mas mesmo CPF, ou mesmos nascimento e mãe: é o titular.
    cpfs = {f["campos"].get("cpf") for f in do_titular} - {None}
    nascimentos = [(f["campos"]["data_nascimento"], f["campos"]["nome_mae"])
                   for f in do_titular if f["campos"].get("data_nascimento") and f["campos"].get("nome_mae")]
    for f in pendentes:
        c = f["campos"]
        dependente = next((d for d in dependentes if regras.mesma_pessoa(d["nome"], c.get("nome"))
                           or (c.get("cpf") and c["cpf"] in {g["campos"].get("cpf") for g in d["fontes"]})), None)
        mesmo_nascimento = any(c.get("data_nascimento") == nasc and regras.mesma_pessoa(c.get("nome_mae"), mae)
                               for nasc, mae in nascimentos)
        if c.get("cpf") in cpfs or mesmo_nascimento:
            do_titular.append(f)
        elif dependente:
            dependente["fontes"].append(f)
        elif any(_nome_contido(d["nome"], c.get("nome")) for d in citados):
            # Enteado, por exemplo: a certidão não tem o funcionário, mas o texto o cita como dependente.
            novo_dependente(c.get("nome"), None, f)["fontes"].append(f)
        else:
            f["pessoa"] = "nao_identificada"
            m.alerta("aviso", None, f"{ROTULOS[f['tipo']]} de uma pessoa que não é o funcionário nem um dependente "
                     "identificado; o conteúdo não foi usado", arquivo=f["arquivo"])

    for f in do_titular:
        f["pessoa"] = "titular"
    for i, d in enumerate(dependentes):
        for f in d["fontes"]:
            f["pessoa"] = f"dependente:{i + 1}"
    return do_titular, dependentes


def _casamento(f: dict, titular: str | None, do_titular: list, novo_dependente, m: _Montagem) -> None:
    c = f["campos"]
    for eu, outro in (("conjuge_1", "conjuge_2"), ("conjuge_2", "conjuge_1")):
        if any(regras.mesma_pessoa(c.get(k), titular) for k in (eu, f"{eu}_nome_apos_casamento")):
            do_titular.append(f)
            nome = c.get(f"{outro}_nome_apos_casamento") or c.get(outro)
            if nome:
                conjuge = {"arquivo": f["arquivo"], "tipo": "conjuge", "tipo_original": "certidao_casamento",
                           "campos": {"nome": nome, "cpf": c.get(f"{outro}_cpf"),
                                      "data_nascimento": c.get(f"{outro}_data_nascimento")}}
                novo_dependente(nome, "conjuge", f)["fontes"].append(conjuge)
                m.alerta("aviso", None, "cônjuge encontrado na certidão de casamento; confirme se é dependente",
                         arquivo=f["arquivo"])
            return
    f["pessoa"] = "nao_identificada"
    m.alerta("aviso", None, "certidão de casamento sem o funcionário entre os cônjuges; o conteúdo não foi usado",
             arquivo=f["arquivo"])


def _deduzidos(do_titular: list[dict]) -> list[dict]:
    """Estado civil esperado pelas certidões e país de nascimento pela certidão ou RG brasileiros."""
    deduzidos = []
    for f in do_titular:
        campos = {}
        if f["tipo"] == "certidao_casamento":
            averbacoes = regras.sem_acento(f["campos"].get("averbacoes") or "").lower()
            campos["estado_civil"] = ("divorciado" if "divorci" in averbacoes else "separado" if "separa" in averbacoes
                                      else "viuvo" if re.search(r"obito|falecim", averbacoes) else "casado")
        if f["tipo"] == "certidao_nascimento":
            anotacoes = regras.sem_acento(f["campos"].get("anotacoes") or "").lower()
            if "casament" not in anotacoes:
                campos["estado_civil"] = "solteiro"
            campos["pais_nascimento"] = "BRASIL"
            # Registro civil brasileiro: nasceu no Brasil, é brasileiro nato.
            campos["nacionalidade"] = "BRASILEIRA"
        if f["tipo"] in ("rg", "cnh") and f["campos"].get("uf_naturalidade" if f["tipo"] == "rg" else "uf_nascimento"):
            campos["pais_nascimento"] = "BRASIL"
        if campos:
            deduzidos.append({"arquivo": f["arquivo"], "tipo": "deduzido", "tipo_original": f["tipo"], "campos": campos})
    # A de casamento é mais recente que a de nascimento: quem casou não é mais solteiro.
    if any(d["tipo_original"] == "certidao_casamento" for d in deduzidos):
        for d in deduzidos:
            if d["tipo_original"] == "certidao_nascimento":
                d["campos"].pop("estado_civil", None)
    return deduzidos


def _nome_de_casada(m: _Montagem, do_titular: list[dict]) -> None:
    """Explica no alerta a divergência de nome que a certidão de casamento justifica."""
    alerta = next((a for a in m.alertas if a["campo"] == "funcionario.nome" and a["tipo"] == "divergente"), None)
    if not alerta:
        return
    nomes = {regras.chave_nome(c["valor"]) for c in alerta["candidatos"]}
    for f in do_titular:
        if f["tipo"] == "certidao_casamento":
            for eu in ("conjuge_1", "conjuge_2"):
                antes, depois = (regras.chave_nome(f["campos"].get(k)) for k in (eu, f"{eu}_nome_apos_casamento"))
                if antes in nomes and depois in nomes:
                    alerta["mensagem"] += "; a certidão de casamento registra a mudança de nome"
                    return


def _problemas(fontes: list[dict], m: _Montagem, caminhos: dict[tuple[str, str], str]) -> None:
    for f in fontes:
        for p in f.get("problemas", []):
            campo = caminhos.get((f["tipo"], p["campo"]), p["campo"] if f["tipo"] == "texto" else f"{f['tipo']}.{p['campo']}")
            m.alerta("invalido", campo, f"{p['mensagem']} ({ROTULOS[f['tipo']]})", arquivo=f["arquivo"], valor=p["valor"])
        for a in f.get("avisos", []):
            m.alerta("aviso", None, a["mensagem"], arquivo=f["arquivo"])


def _hoje() -> str:
    return date.today().isoformat()


def _conferir_funcionario(ficha: dict, m: _Montagem) -> None:
    func, contrato = ficha["funcionario"], ficha["contrato"]
    nascimento = func["data_nascimento"]
    referencia = contrato["data_admissao"] or _hoje()
    if nascimento:
        anos = regras.idade(nascimento, referencia)
        if not 14 <= anos <= 100:
            m.alerta("invalido", "funcionario.data_nascimento", "idade na admissão fora de 14 a 100 anos")
        elif anos < 16:
            m.alerta("aviso", "funcionario.data_nascimento", "menor de 16 anos: só pode ser admitido como aprendiz")
    rg, cnh, endereco = func["rg"] or {}, func["cnh"] or {}, func["endereco"] or {}
    if nascimento and rg.get("data_expedicao") and rg["data_expedicao"] < nascimento:
        m.alerta("invalido", "funcionario.rg.data_expedicao", "RG expedido antes do nascimento")
    if cnh.get("validade") and cnh["validade"] < _hoje():
        m.alerta("aviso", "funcionario.cnh.validade", "CNH vencida")
    if endereco.get("cep") and endereco.get("uf") and regras.uf_do_cep(endereco["cep"]) not in (None, endereco["uf"]):
        m.alerta("invalido", "funcionario.endereco.cep", "CEP não pertence à UF do endereço")
    if endereco.get("titular") and func["nome"] and not regras.mesma_pessoa(endereco["titular"], func["nome"]):
        m.alerta("aviso", "funcionario.endereco.titular", "titular do comprovante de residência não é o funcionário")
    if endereco.get("data_referencia") and regras.dias_entre(endereco["data_referencia"], _hoje()) > 90:
        m.alerta("aviso", "funcionario.endereco.data_referencia", "comprovante de residência com mais de 90 dias")


def _conferir_contrato(contrato: dict, m: _Montagem) -> None:
    admissao, tipo = contrato["data_admissao"], contrato["tipo_contrato"]
    experiencia, horario, aso = contrato["experiencia"] or {}, contrato["horario"] or {}, contrato["aso"] or {}
    if admissao and not -30 <= regras.dias_entre(_hoje(), admissao) <= 60:
        m.alerta("aviso", "contrato.data_admissao", "data de admissão a mais de 30 dias atrás ou 60 dias à frente")
    if tipo == "experiencia" and not experiencia.get("dias"):
        m.alerta("ausente", "contrato.experiencia.dias", "contrato de experiência sem o prazo")
    if sum(filter(None, (experiencia.get("dias"), experiencia.get("prorrogacao_dias")))) > 90:
        m.alerta("invalido", "contrato.experiencia", "experiência com prorrogação passa de 90 dias")
    if tipo == "determinado" and not contrato["data_termino"]:
        m.alerta("ausente", "contrato.data_termino", "contrato por prazo determinado sem a data de término")
    if admissao and contrato["data_termino"]:
        dias = regras.dias_entre(admissao, contrato["data_termino"])
        if dias <= 0:
            m.alerta("invalido", "contrato.data_termino", "término antes da admissão")
        elif dias > 730:
            m.alerta("aviso", "contrato.data_termino", "prazo determinado de mais de 2 anos")
    if horario.get("entrada") and horario.get("saida") and horario["saida"] <= horario["entrada"]:
        m.alerta("aviso", "contrato.horario.saida", "saída antes da entrada: confira se a jornada é noturna")
    if (contrato["jornada_semanal_horas"] or 0) > 44:
        m.alerta("aviso", "contrato.jornada_semanal_horas", "jornada semanal acima de 44 horas")
    if aso.get("data") and admissao and aso["data"] > admissao:
        m.alerta("aviso", "contrato.aso.data", "ASO depois da data de admissão")
    if aso.get("apto") is False:
        m.alerta("aviso", "contrato.aso.apto", "ASO sem aptidão")


def _dependentes(dependentes: list[dict], texto: dict | None, titular: dict, m: _Montagem) -> list[dict]:
    for lido in (texto or {}).get("dependentes", []):
        d = next((d for d in dependentes if _nome_contido(lido["nome"], d["nome"]) or _nome_contido(d["nome"], lido["nome"])), None)
        if d is None:
            d = {"nome": lido["nome"], "fontes": [], "sem_documento": True}
            dependentes.append(d)
        trechos = {c: lido["trecho"] for c in ("nome", "parentesco", "irrf", "salario_familia")}
        d["fontes"].append({"arquivo": "texto", "tipo": "texto", "trechos": trechos,
                            "campos": {k: v for k, v in lido.items() if k != "trecho"}})

    fichas = []
    for i, d in enumerate(dependentes):
        prefixo = f"dependentes[{i}]"
        ficha: dict = {}
        mapa = DEPENDENTE | {"nome": DEPENDENTE["nome"] + ([("texto", "nome")] if d.get("sem_documento") else [])}
        for campo, fontes_campo in mapa.items():
            valor = m.decidir(f"{prefixo}.{campo}", fontes_campo, d["fontes"])
            _definir(ficha, campo, valor)
        if d.get("sem_documento"):
            m.alerta("aviso", f"{prefixo}.nome", "dependente citado no texto sem documento")
        for campo in ESPERADOS_DEPENDENTE:
            if ficha[campo] is None and f"{prefixo}.{campo}" not in m.campos_com_alerta():
                m.alerta("ausente", f"{prefixo}.{campo}", f"{prefixo}.{campo} não encontrado")
        nascimento, nascimento_titular = ficha["data_nascimento"], titular["data_nascimento"]
        if ficha["parentesco"] == "filho" and nascimento and nascimento_titular and \
                regras.idade(nascimento_titular, nascimento) < 12:
            m.alerta("aviso", f"{prefixo}.data_nascimento", "filho com menos de 12 anos de diferença do funcionário")
        if ficha["salario_familia"] and nascimento and regras.idade(nascimento, _hoje()) >= 14:
            m.alerta("aviso", f"{prefixo}.salario_familia", "salário-família para dependente com 14 anos ou mais")
        fichas.append(_esvaziar(ficha))
    return fichas


def montar(arquivos: list[dict], texto: dict | None) -> dict:
    """Junta os arquivos lidos (documentos.ler_arquivo, ou com status erro) e o texto lido numa ficha.

    Devolve ficha, origens, alertas e o resumo de cada arquivo (tipos lidos e de quem é).
    """
    m = _Montagem()
    fontes = [f for a in arquivos if a["status"] == "ok" for f in a["fontes"]]
    for a in arquivos:
        if a["status"] == "ok":
            for aviso in a.get("avisos", []):
                m.alerta("aviso", None, aviso["mensagem"], arquivo=a["arquivo"])
        else:
            m.alerta("aviso", None, "arquivo não foi lido; os dados dele estão faltando", arquivo=a["arquivo"])

    do_titular, dependentes = _identificar(fontes, texto, m)
    texto_fontes = [texto] if texto else []
    titular_fontes = do_titular + _deduzidos(do_titular) + texto_fontes

    caminhos = {(t, c): caminho for caminho, mapa in TITULAR.items() for t, c in mapa}
    _problemas(do_titular + texto_fontes, m, caminhos)
    for i, d in enumerate(dependentes):
        _problemas([f for f in d["fontes"] if "problemas" in f], m,
                   {(t, c): f"dependentes[{i}].{campo}" for campo, mapa in DEPENDENTE.items() for t, c in mapa})

    ficha: dict = {"funcionario": {}, "dependentes": [], "contrato": {}}
    for caminho, mapa in TITULAR.items():
        _definir(ficha, caminho, m.decidir(caminho, mapa, titular_fontes))
    _nome_de_casada(m, do_titular)

    nome_texto = (texto or {}).get("campos", {}).get("funcionario.nome")
    nome = ficha["funcionario"]["nome"]
    if nome_texto and nome and not (_nome_contido(nome_texto, nome) or _mesmo_nome(nome_texto, nome)):
        m.alerta("aviso", "funcionario.nome", "o nome citado no texto difere do nome nos documentos",
                 candidatos=[{"valor": nome_texto, **_ref(texto, "funcionario.nome")}])

    if _mesmo_nome(ficha["funcionario"].get("nome_social"), ficha["funcionario"]["nome"]):
        # Formulário que repete o nome civil no campo de nome social: não há nome social.
        ficha["funcionario"]["nome_social"] = None
        m.origens.pop("funcionario.nome_social", None)
    ficha["funcionario"] = _esvaziar(ficha["funcionario"])
    ficha["contrato"] = _esvaziar(ficha["contrato"])
    ficha["dependentes"] = _dependentes(dependentes, texto, ficha["funcionario"], m)
    ficha["outras_informacoes"] = (texto or {}).get("outras_informacoes", [])

    _conferir_funcionario(ficha, m)
    _conferir_contrato(ficha["contrato"], m)
    com_alerta = m.campos_com_alerta()
    faltando = " (há arquivos que não foram lidos)" if any(a["status"] != "ok" for a in arquivos) else ""
    for caminho in ESPERADOS:
        if _valor(ficha, caminho) is None and caminho not in com_alerta:
            m.alerta("ausente", caminho, f"{caminho} não encontrado nos documentos nem no texto{faltando}")

    resumo = []
    for a in arquivos:
        item = {k: a[k] for k in ("arquivo", "status", "paginas_lidas", "erro", "relido") if k in a}
        if a["status"] == "ok":
            item["tipos"] = [f["tipo"] for f in a["fontes"]]
            item["descricoes"] = [f.get("descricao") for f in a["fontes"]]
            item["pessoas"] = list(dict.fromkeys(f.get("pessoa", "titular") for f in a["fontes"] if f["tipo"] != "outro"))
        resumo.append(item)
    return {"documentos": resumo, "ficha": ficha, "origens": m.origens, "alertas": m.alertas,
            "_reler": _releituras(m.divergencias)}


def _releituras(divergencias: dict[str, list[tuple[dict, str]]]) -> dict[str, list[str]]:
    """Arquivo → campos a reler: os de dígitos e letras em que documentos divergiram.

    Só o nome do campo vai para o agy, nunca o valor de um lado ou de outro.
    """
    pedidos: dict[str, list[str]] = {}
    for caminho, envolvidos in divergencias.items():
        campo = re.sub(r"^dependentes\[\d+\]\.", "", caminho)
        if caminho not in RELER_SE_DIVERGIR and not (caminho.startswith("dependentes[") and campo in RELER_DEPENDENTE):
            continue
        for fonte, campo_documento in envolvidos:
            if fonte["tipo"] in ROTULOS and fonte["tipo"] not in ("texto", "deduzido"):
                descricao = f"{campo_documento} ({ROTULOS[fonte['tipo']]})"
                pedidos.setdefault(fonte["arquivo"], [])
                if descricao not in pedidos[fonte["arquivo"]]:
                    pedidos[fonte["arquivo"]].append(descricao)
    return pedidos

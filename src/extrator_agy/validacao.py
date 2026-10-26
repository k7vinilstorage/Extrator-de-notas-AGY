"""Validação e normalização locais dos dados extraídos, sem depender do modelo.

A chave de acesso tem dígito verificador e repete UF, ano/mês, CNPJ/CPF e
número da nota, então dá para conferir se a leitura desses campos bate. Vale
para a chave de 44 posições (NF-e, NFC-e, CF-e SAT) e para a de 50 da NFS-e
nacional.
"""

import re
from datetime import date

# Código IBGE da UF (os 2 primeiros dígitos da chave)
UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO",
    "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL",
    "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR",
    "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF",
}


def alfanum(texto: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (texto or "").upper())


def digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _valor(c: str) -> int:
    # Para dígitos é o próprio número; letras do CNPJ alfanumérico (a partir de
    # 2026) valem o código ASCII menos 48, como define a Receita Federal.
    return ord(c) - 48


def dv_chave(base: str) -> int:
    soma, peso = 0, 2
    for c in reversed(base):
        soma += _valor(c) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def _dv_pesos(base: str, pesos: list[int]) -> int:
    resto = sum(_valor(c) * p for c, p in zip(base, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cnpj_valido(cnpj: str | None) -> bool:
    c = alfanum(cnpj)
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c) or len(set(c)) == 1:
        return False
    dv1 = _dv_pesos(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    dv2 = _dv_pesos(c[:12] + str(dv1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return c[12:] == f"{dv1}{dv2}"


def cpf_valido(cpf: str | None) -> bool:
    c = digitos(cpf)
    if len(c) != 11 or len(set(c)) == 1:
        return False
    dv1 = _dv_pesos(c[:9], list(range(10, 1, -1)))
    dv2 = _dv_pesos(c[:10], list(range(11, 1, -1)))
    return c[9:] == f"{dv1}{dv2}"


def chave_valida(chave: str | None) -> bool:
    # Na NFS-e o DV também é módulo 11 com pesos de 2 a 9, sobre as 49 posições anteriores.
    c = alfanum(chave)
    return len(c) in (44, 50) and dv_chave(c[:-1]) == _valor(c[-1])


def decompor_chave(chave: str) -> dict:
    """Separa os campos de uma chave de 44 posições (NF-e/NFC-e ou CF-e SAT) ou de 50 (NFS-e)."""
    if len(chave) == 50:
        # Município IBGE (7, começa pelo código da UF), ambiente, tipo de inscrição,
        # CPF/CNPJ (14), número (13), ano/mês de emissão, código numérico (9) e DV.
        return {"uf": chave[0:2], "aamm": chave[36:40], "cpf_cnpj": chave[9:23], "modelo": "nfse",
                "numero": chave[23:36]}
    modelo = chave[20:22]
    numero = chave[31:37] if modelo == "59" else chave[25:34]
    return {"uf": chave[0:2], "aamm": chave[2:6], "cpf_cnpj": chave[6:20], "modelo": modelo, "numero": numero}


def formatar_cpf_cnpj(valor: str | None) -> str | None:
    c = alfanum(valor)
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    if len(c) == 11 and c.isdigit():
        return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
    return valor


def data_iso(texto: str | None) -> str | None:
    """A data em AAAA-MM-DD, sem hora. Aceita também DD/MM/AAAA; None se não for uma data válida."""
    t = (texto or "").strip()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", t):
        ano, mes, dia = m.groups()
    elif m := re.match(r"(\d{2})/(\d{2})/(\d{4})", t):
        dia, mes, ano = m.groups()
    else:
        return None
    try:
        return date(int(ano), int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def normalizar(dados: dict) -> dict:
    """Padroniza os formatos e completa pela chave o que o modelo não leu."""
    d = dict(dados)
    # Data que não dá para entender fica como veio, para a validação acusar.
    d["data_emissao"] = data_iso(d.get("data_emissao")) or (d.get("data_emissao") or "").strip() or None
    d["chave_acesso"] = alfanum(d.get("chave_acesso")) or None
    d["numero_nota"] = str(int(digitos(d.get("numero_nota")))) if digitos(d.get("numero_nota")) else None
    d["uf"] = (d.get("uf") or "").strip().upper() or None
    d["municipio"] = (d.get("municipio") or "").strip().upper() or None

    if chave_valida(d["chave_acesso"]):
        p = decompor_chave(d["chave_acesso"])
        if not d["cpf_cnpj"]:
            # Emitente pessoa física aparece na chave como CPF com zeros à esquerda.
            d["cpf_cnpj"] = p["cpf_cnpj"][3:] if p["cpf_cnpj"].startswith("000") and cpf_valido(p["cpf_cnpj"][3:]) else p["cpf_cnpj"]
        d["uf"] = d["uf"] or UF_POR_CODIGO.get(p["uf"])
        d["numero_nota"] = d["numero_nota"] or str(int(p["numero"]))

    d["cpf_cnpj"] = formatar_cpf_cnpj(d.get("cpf_cnpj"))

    # Só em DANFE de NF-e; nos demais documentos (e lista vazia) fica null.
    itens = d.get("itens") if isinstance(d.get("itens"), list) else []
    d["itens"] = [
        {"descricao": (i.get("descricao") or "").strip() or None, "ncm": digitos(str(i.get("ncm") or "")) or None}
        for i in itens if isinstance(i, dict)
    ] or None
    return d


def problemas_itens(itens: list[dict] | None, texto: str | None = None) -> list[str]:
    """NCM com 8 dígitos e, se o PDF tem camada de texto, impresso nele."""
    problemas = []
    texto = re.sub(r"\s", "", texto or "")
    for n, item in enumerate(itens or [], 1):
        ncm = item.get("ncm")
        if ncm and not re.fullmatch(r"\d{8}", ncm):
            problemas.append(f"NCM inválido ({ncm}) no item {n}")
        elif ncm and texto and ncm not in texto:
            problemas.append(f"NCM {ncm} do item {n} não aparece no texto do PDF")
    return problemas


def validar(dados: dict, texto: str | None = None) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia se estiver tudo certo).

    texto é a camada de texto do PDF, quando houver, para conferir o NCM dos itens.
    """
    problemas = problemas_itens(dados.get("itens"), texto)
    doc = alfanum(dados.get("cpf_cnpj"))
    if doc and not (cnpj_valido(doc) if len(doc) == 14 else cpf_valido(doc)):
        problemas.append(f"CPF/CNPJ inválido ({dados['cpf_cnpj']})")

    data = dados.get("data_emissao") or ""
    if data and not data_iso(data):
        problemas.append(f"data de emissão inválida ({data})")

    chave = alfanum(dados.get("chave_acesso"))
    if not chave:
        return problemas
    if len(chave) not in (44, 50):
        return problemas + [f"chave de acesso com {len(chave)} caracteres (esperado 44, ou 50 na NFS-e)"]
    if not chave_valida(chave):
        return problemas + ["dígito verificador da chave inválido"]

    p = decompor_chave(chave)
    if doc and doc.zfill(14) != p["cpf_cnpj"]:
        problemas.append(f"CPF/CNPJ ({doc}) difere do da chave ({p['cpf_cnpj']})")

    numero = digitos(dados.get("numero_nota"))
    if numero and int(numero) != int(p["numero"]):
        problemas.append(f"número da nota ({numero}) difere do da chave ({int(p['numero'])})")

    if re.match(r"\d{4}-\d{2}", data) and data[2:4] + data[5:7] != p["aamm"]:
        problemas.append(f"data de emissão ({data[:7]}) difere do ano/mês da chave ({p['aamm']})")

    uf = dados.get("uf")
    if uf and UF_POR_CODIGO.get(p["uf"]) not in (None, uf.upper()):
        problemas.append(f"UF ({uf}) difere da UF da chave ({UF_POR_CODIGO[p['uf']]})")

    if p["modelo"] == "55" and not dados.get("itens"):
        problemas.append("itens da NF-e não lidos")

    return problemas

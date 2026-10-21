"""Validação e normalização locais dos dados extraídos, sem depender do modelo.

A chave de acesso tem dígito verificador e repete UF, ano/mês, CNPJ/CPF e
número da nota, então dá para conferir se a leitura desses campos bate.
"""

import re

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
    c = alfanum(chave)
    return len(c) == 44 and dv_chave(c[:43]) == _valor(c[43])


def decompor_chave(chave: str) -> dict:
    """Separa os campos de uma chave de 44 posições (NF-e/NFC-e ou CF-e SAT)."""
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


def normalizar(dados: dict) -> dict:
    """Padroniza os formatos e completa pela chave o que o modelo não leu."""
    d = dict(dados)
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
    return d


def validar(dados: dict) -> list[str]:
    """Retorna a lista de problemas encontrados (vazia se estiver tudo certo)."""
    problemas = []
    doc = alfanum(dados.get("cpf_cnpj"))
    if doc and not (cnpj_valido(doc) if len(doc) == 14 else cpf_valido(doc)):
        problemas.append(f"CPF/CNPJ inválido ({dados['cpf_cnpj']})")

    chave = alfanum(dados.get("chave_acesso"))
    if not chave:
        return problemas
    if len(chave) != 44:
        return problemas + [f"chave de acesso com {len(chave)} caracteres (esperado 44)"]
    if not chave_valida(chave):
        return problemas + ["dígito verificador da chave inválido"]

    p = decompor_chave(chave)
    if doc and doc.zfill(14) != p["cpf_cnpj"]:
        problemas.append(f"CPF/CNPJ ({doc}) difere do da chave ({p['cpf_cnpj']})")

    numero = digitos(dados.get("numero_nota"))
    if numero and int(numero) != int(p["numero"]):
        problemas.append(f"número da nota ({numero}) difere do da chave ({int(p['numero'])})")

    data = dados.get("data_emissao") or ""
    if re.match(r"\d{4}-\d{2}", data) and data[2:4] + data[5:7] != p["aamm"]:
        problemas.append(f"data de emissão ({data[:7]}) difere do ano/mês da chave ({p['aamm']})")

    uf = dados.get("uf")
    if uf and UF_POR_CODIGO.get(p["uf"]) not in (None, uf.upper()):
        problemas.append(f"UF ({uf}) difere da UF da chave ({UF_POR_CODIGO[p['uf']]})")

    return problemas

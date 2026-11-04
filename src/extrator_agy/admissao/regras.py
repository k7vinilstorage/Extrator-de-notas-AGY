"""Validações e conversões puras dos dados de admissão, sem depender do modelo.

`normalizar(formato, valor)` devolve (valor normalizado, None) ou (None, problema).
O problema nunca repete o valor lido: ele vai para o prompt da releitura, e
dado pessoal não deve ir parar lá.
"""

import re
import unicodedata
from datetime import date

from ..validacao import _dv_pesos, cpf_valido, data_iso, digitos

UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
    "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

NOMES_UF = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAZONAS": "AM", "AMAPA": "AP", "BAHIA": "BA", "CEARA": "CE",
    "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA", "MINAS GERAIS": "MG",
    "MATO GROSSO DO SUL": "MS", "MATO GROSSO": "MT", "PARA": "PA", "PARAIBA": "PB", "PERNAMBUCO": "PE",
    "PIAUI": "PI", "PARANA": "PR", "RIO DE JANEIRO": "RJ", "RIO GRANDE DO NORTE": "RN", "RONDONIA": "RO",
    "RORAIMA": "RR", "RIO GRANDE DO SUL": "RS", "SANTA CATARINA": "SC", "SERGIPE": "SE", "SAO PAULO": "SP",
    "TOCANTINS": "TO",
}

# Código da UF nos dígitos 9 e 10 do título de eleitor (28 é o exterior).
UF_TITULO = {
    "01": "SP", "02": "MG", "03": "RJ", "04": "RS", "05": "BA", "06": "PR", "07": "CE", "08": "PE",
    "09": "SC", "10": "GO", "11": "MA", "12": "PB", "13": "PA", "14": "ES", "15": "PI", "16": "RN",
    "17": "AL", "18": "MT", "19": "MS", "20": "DF", "21": "SE", "22": "AM", "23": "RO", "24": "AC",
    "25": "AP", "26": "RR", "27": "TO", "28": "ZZ",
}

# Faixas de CEP (5 primeiros dígitos) por UF, dos Correios. CEP fora de todas não é acusado.
FAIXAS_CEP = [
    (1000, 19999, "SP"), (20000, 28999, "RJ"), (29000, 29999, "ES"), (30000, 39999, "MG"),
    (40000, 48999, "BA"), (49000, 49999, "SE"), (50000, 56999, "PE"), (57000, 57999, "AL"),
    (58000, 58999, "PB"), (59000, 59999, "RN"), (60000, 63999, "CE"), (64000, 64999, "PI"),
    (65000, 65999, "MA"), (66000, 68899, "PA"), (68900, 68999, "AP"), (69000, 69299, "AM"),
    (69300, 69399, "RR"), (69400, 69899, "AM"), (69900, 69999, "AC"), (70000, 72799, "DF"),
    (72800, 72999, "GO"), (73000, 73699, "DF"), (73700, 76799, "GO"), (76800, 76999, "RO"),
    (77000, 77999, "TO"), (78000, 78899, "MT"), (79000, 79999, "MS"), (80000, 87999, "PR"),
    (88000, 89999, "SC"), (90000, 99999, "RS"),
]

DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44,
    45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81,
    82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}

CATEGORIAS_CNH = {"A", "B", "AB", "C", "D", "E", "AC", "AD", "AE", "ACC"}

PARTICULAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}

# Tipo do livro na matrícula da certidão (posição 15): 1 é o livro A (nascimento),
# 2 o B (casamento) e 3 o B auxiliar (casamento religioso com efeito civil).
LIVRO_MATRICULA = {"certidao_nascimento": {"1"}, "certidao_casamento": {"2", "3"}}


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def chave_nome(nome: str | None) -> str:
    """O nome só para comparar: maiúsculas, sem acento, sem pontuação e sem partículas.

    Letra seguida de ponto é inicial, não partícula: o "E." de "MARIA E. SILVA" fica.
    """
    palavras = re.findall(r"[A-Z]+\.?", sem_acento(nome or "").upper())
    return " ".join(p.rstrip(".") for p in palavras if p.endswith(".") or p not in PARTICULAS)


def _mesma_palavra(a: str, b: str) -> bool:
    # "E" (de "E.") é a inicial de "EXEMPLO".
    return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def abreviacao(a: str | None, b: str | None) -> bool:
    """O mesmo nome, com ou sem iniciais no lugar de palavras: "MARIA E. DA SILVA" e "MARIA EXEMPLO DA SILVA".

    O primeiro nome e o sobrenome têm de estar por extenso e iguais nos dois.
    """
    x, y = chave_nome(a).split(), chave_nome(b).split()
    return (len(x) == len(y) >= 2 and x[0] == y[0] and x[-1] == y[-1]
            and all(_mesma_palavra(p, q) for p, q in zip(x, y)))


def mesma_pessoa(a: str | None, b: str | None) -> bool:
    """Nomes que podem ser da mesma pessoa: iguais, abreviados ou com nomes do meio omitidos.

    Serve para decidir de quem é um documento, não para dizer que dois valores são iguais.
    """
    x, y = chave_nome(a).split(), chave_nome(b).split()
    if not x or not y or x[0] != y[0] or x[-1] != y[-1]:
        return False
    # "D." e "E." abreviam partículas ("DE", "E"), que a comparação já ignora.
    x, y = ([p for p in nome if p not in ("D", "E")] for nome in (x, y))
    curto, longo = (x, y) if len(x) <= len(y) else (y, x)
    j = 0
    for palavra in curto:
        while j < len(longo) and not _mesma_palavra(palavra, longo[j]):
            j += 1
        if j == len(longo):
            return False
        j += 1
    return True


def nome_mais_completo(nomes: list[str]) -> str:
    """Entre abreviações do mesmo nome, a que tem mais letras por extenso."""
    return max(nomes, key=lambda n: len(chave_nome(n).replace(" ", "")))


def _minusculo(texto: str) -> str:
    return sem_acento(texto).lower()


def pis_valido(pis: str | None) -> bool:
    p = digitos(pis)
    return len(p) == 11 and len(set(p)) > 1 and _dv_pesos(p[:10], [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]) == int(p[10])


def _dv_titulo(soma: int, uf: str) -> int:
    resto = soma % 11
    if resto == 10:
        return 0
    # Em SP e MG, resto 0 vira DV 1.
    return 1 if resto == 0 and uf in ("01", "02") else resto


def titulo_valido(numero: str | None) -> bool:
    """Título de eleitor com 12 dígitos: 8 do sequencial, 2 da UF e 2 de DV.

    Títulos antigos de SP e MG têm 13 dígitos (sequencial de 9); neles só se confere a UF.
    """
    t = digitos(numero)
    if len(t) not in (12, 13) or t[-4:-2] not in UF_TITULO:
        return False
    if len(t) == 13:
        return True
    sequencial, uf, dv = t[:8], t[8:10], t[10:]
    dv1 = _dv_titulo(sum(int(d) * p for d, p in zip(sequencial, range(2, 10))), uf)
    dv2 = _dv_titulo(int(uf[0]) * 7 + int(uf[1]) * 8 + dv1 * 9, uf)
    return dv == f"{dv1}{dv2}"


def uf_do_titulo(numero: str | None) -> str | None:
    t = digitos(numero)
    return UF_TITULO.get(t[-4:-2]) if len(t) in (12, 13) else None


def uf_do_cep(cep: str | None) -> str | None:
    c = digitos(cep)
    if len(c) != 8:
        return None
    prefixo = int(c[:5])
    return next((uf for inicio, fim, uf in FAIXAS_CEP if inicio <= prefixo <= fim), None)


def idade(nascimento: str, em: str) -> int:
    n, e = date.fromisoformat(nascimento), date.fromisoformat(em)
    return e.year - n.year - ((e.month, e.day) < (n.month, n.day))


def dias_entre(inicio: str, fim: str) -> int:
    return (date.fromisoformat(fim) - date.fromisoformat(inicio)).days


def dinheiro(texto: str | None) -> float | None:
    """Valor em reais como costuma ser escrito: R$ 2.500,00, 2500, 2.500, 2500,00 ou 2500.00."""
    t = re.sub(r"(?i)^\s*r\$\s*", "", texto or "").strip().rstrip(".")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+,\d{1,2}", t):
        t = t.replace(",", ".")
    elif not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    return round(float(t), 2)


def hora(texto: str | None) -> str | None:
    """8h, 8:30, 08h30, 17:00 → HH:MM."""
    m = re.fullmatch(r"(\d{1,2})\s*(?:[:h]\s*(\d{2})?\s*(?:h|hs|min)?)?", (texto or "").strip().lower())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def duracao_minutos(texto: str | None) -> int | None:
    """1h, 1h30, 1:30, 90 min, 60 minutos, 2 horas → minutos."""
    t = _minusculo(texto or "").strip()
    if m := re.fullmatch(r"(\d+)\s*(?:min|mins|minutos?)", t):
        return int(m.group(1))
    if m := re.fullmatch(r"(\d+)\s*(?:h|hs|horas?)\s*(?:(\d{1,2})\s*(?:min|minutos?)?)?", t):
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    if m := re.fullmatch(r"(\d+):(\d{2})", t):
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


# Palavras que podem cercar um número sem mudar o que ele quer dizer ("mais 60 dias").
LIGACAO = r"dias?|horas?|h|anos?|meses|mes|mais|por|de|ate|\+|prorrogave(?:l|is)|prorrogacao|prorrogado|uteis|corridos"


def inteiro(texto: str | None) -> int | None:
    """O único número inteiro do texto ("45", "45 dias", "mais 60"); None se houver zero ou mais de um."""
    numeros = re.findall(r"\d+", texto or "")
    sobra = re.sub(rf"\d+|\b(?:{LIGACAO})\b|\+", "", _minusculo(texto or "")).strip()
    return int(numeros[0]) if len(numeros) == 1 and not sobra else None


def numero(texto: str | None) -> float | None:
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:h|hs|horas?)?", (texto or "").strip().lower())
    return float(m.group(1).replace(",", ".")) if m else None


def _por_palavra(texto: str | None, tabela: list[tuple[str, str]]) -> str | None:
    t = _minusculo(texto or "")
    return next((valor for padrao, valor in tabela if re.search(padrao, t)), None)


ESTADO_CIVIL = [
    (r"uniao estavel|amasiad|convivente", "uniao_estavel"),
    (r"solteir", "solteiro"), (r"casad", "casado"), (r"divorciad", "divorciado"),
    (r"separad", "separado"), (r"viuv", "viuvo"),
]

# "Negro" não entra: no IBGE ele junta preta e parda, então não define uma das duas.
RACA_COR = [
    (r"nao (?:informad|declarad|quer|desej)|prefere nao", "nao_informado"),
    (r"branc", "branca"), (r"pret", "preta"), (r"pard", "parda"), (r"amarel", "amarela"),
    (r"indigen", "indigena"),
]

TIPO_CONTRATO = [
    (r"experiencia", "experiencia"), (r"indeterminad|efetiv", "indeterminado"),
    (r"determinad|temporari", "determinado"),
]

TIPO_SALARIO = [
    (r"\bmes\b|mensal", "mensal"), (r"quinzen", "quinzenal"), (r"seman", "semanal"),
    (r"\bdia\b|diari", "diario"), (r"hora|horista", "horista"), (r"tarefa|producao", "tarefa"),
]

PARENTESCO = [
    (r"entead", "enteado"), (r"filh", "filho"), (r"companheir", "companheiro"),
    (r"conjuge|espos|marido|mulher", "conjuge"),
]

SEXO = [(r"^\s*(?:m|masc|masculin[oa]|homem)\s*$", "M"), (r"^\s*(?:f|fem|feminin[oa]|mulher)\s*$", "F")]

SIM_NAO = [(r"^\s*(?:nao|n)\b", False), (r"^\s*(?:sim|s)\b", True)]

INCOMPLETO = r"incomplet|cursando|trancad|em andamento|interromp|nao conclu"
COMPLETO = r"complet|conclu|formad|diploma|certificad|bacharel|licenciad"


def grau_instrucao(texto: str | None) -> str | None:
    """Grau de instrução (enum da ficha) pelo nível e situação escritos; None se não der para saber.

    Fundamental incompleto não define o grau (o eSocial separa até o 5º ano, o 5º
    completo e do 6º ao 9º), nem um nível sem dizer se foi concluído.
    """
    t = _minusculo(texto or "")  # "2º grau" vira "2o grau"
    incompleto = bool(re.search(INCOMPLETO, t))
    completo = not incompleto and bool(re.search(COMPLETO, t))
    if re.search(r"analfabet", t):
        return "analfabeto"
    for padrao, nivel in ((r"doutor", "doutorado"), (r"mestr", "mestrado"),
                          (r"pos[- ]?gradua|especializa|\bmba\b", "pos_graduacao")):
        if re.search(padrao, t):
            return "superior_completo" if incompleto else nivel if completo else None
    if re.search(r"superior|gradua|faculdade|bacharel|licenciatura|tecnolog", t):
        return "superior_incompleto" if incompleto else "superior_completo" if completo else None
    if re.search(r"medio|2\W?o? grau|segundo grau|colegial", t):
        return "medio_incompleto" if incompleto else "medio_completo" if completo else None
    if re.search(r"fundamental|1\W?o? grau|primeiro grau|ginasi", t):
        return "fundamental_completo" if completo else None
    return None


MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
MESES |= {nome[:3]: n for nome, n in MESES.items()}


def _mes_por_extenso(valor: str) -> str:
    """"24 de junho de 1998", "1º de maio de 2000" e "24/JUN/1998" → "24/06/1998"; o resto fica como veio."""
    t = sem_acento(valor).lower().strip()
    m = (re.fullmatch(r"(\d{1,2})\s*[ºo°]?\s+de\s+([a-z]+)\s+de\s+(\d{4})\.?", t)
         or re.fullmatch(r"(\d{1,2})\s*[/. -]\s*([a-z]{3,9})\.?\s*[/. -]\s*(\d{4})", t))
    if m and m.group(2) in MESES:
        return f"{int(m.group(1)):02d}/{MESES[m.group(2)]:02d}/{m.group(3)}"
    return valor


def _data(valor: str, futura: bool) -> tuple:
    # A CIN e outros documentos imprimem "05 / 03 / 1990"; certidões, às vezes, "05.03.1990" ou
    # "24 DE JUNHO DE 1998".
    valor = _mes_por_extenso(valor)
    iso = data_iso(re.sub(r"^(\d{2})\s*[/.-]\s*(\d{2})\s*[/.-]\s*(\d{4})", r"\1/\2/\3", valor.strip()))
    if not iso or iso < "1900-01-01":
        return None, "data inválida"
    if not futura and iso > date.today().isoformat():
        return None, "data no futuro"
    return iso, None


def _texto(valor: str) -> str:
    return re.sub(r"\s+", " ", valor).strip()


def _enum(tabela: list, nome: str):
    def converter(valor: str) -> tuple:
        convertido = _por_palavra(valor, tabela)
        return (convertido, None) if convertido is not None else (None, f"{nome} não reconhecido")
    return converter


def _com_digitos(tamanhos: tuple[int, ...], nome: str, valida=None):
    def converter(valor: str) -> tuple:
        d = digitos(valor)
        if len(d) not in tamanhos or (valida and not valida(d)):
            return None, f"{nome} inválido"
        return d, None
    return converter


def _cpf(valor: str) -> tuple:
    d = digitos(valor)
    if not cpf_valido(d):
        return None, "CPF com dígito verificador inválido" if len(d) == 11 else "CPF sem 11 dígitos"
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}", None


def _pis(valor: str) -> tuple:
    d = digitos(valor)
    if not pis_valido(d):
        return None, "PIS com dígito verificador inválido" if len(d) == 11 else "PIS sem 11 dígitos"
    return f"{d[:3]}.{d[3:8]}.{d[8:10]}-{d[10]}", None


def _cep(valor: str) -> tuple:
    d = digitos(valor)
    return (f"{d[:5]}-{d[5:]}", None) if len(d) == 8 else (None, "CEP sem 8 dígitos")


def _uf(valor: str) -> tuple:
    # Certidões antigas escrevem o estado por extenso ("AMAZONAS").
    uf = re.sub(r"\s+", " ", sem_acento(valor).strip().upper().removeprefix("ESTADO DO ").removeprefix("ESTADO DE "))
    uf = NOMES_UF.get(uf, uf)
    return (uf, None) if uf in UFS else (None, "UF inválida")


def _telefone(valor: str) -> tuple:
    d = digitos(valor)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11) or int(d[:2]) not in DDDS:
        return None, "telefone sem DDD válido"
    return d, None


def _email(valor: str) -> tuple:
    e = valor.strip().lower()
    return (e, None) if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) else (None, "e-mail inválido")


def _categoria_cnh(valor: str) -> tuple:
    c = re.sub(r"\W", "", valor.upper())
    return (c, None) if c in CATEGORIAS_CNH else (None, "categoria da CNH inválida")


def _escala(valor: str) -> tuple:
    m = re.search(r"(\d{1,2})\s*[x×/]\s*(\d{1,2})", valor.lower())
    return (f"{m.group(1)}x{m.group(2)}", None) if m else (None, "escala não reconhecida")


def _conversor(funcao, nome: str):
    def converter(valor: str) -> tuple:
        convertido = funcao(valor)
        return (convertido, None) if convertido is not None else (None, f"{nome} não reconhecido")
    return converter


FORMATOS = {
    "texto": lambda v: (_texto(v), None),
    "maiusculo": lambda v: (_texto(v).upper(), None),
    "nome": lambda v: (_texto(v).upper(), None) if chave_nome(v) else (None, "nome ilegível"),
    "cpf": _cpf,
    "pis": _pis,
    "data": lambda v: _data(v, futura=False),
    "data_futura": lambda v: _data(v, futura=True),
    "uf": _uf,
    "cep": _cep,
    "titulo": _com_digitos((12, 13), "número do título", titulo_valido),
    "cnh": _com_digitos((11,), "registro da CNH"),
    "matricula": _com_digitos((32,), "matrícula da certidão"),
    "cbo": _com_digitos((6,), "CBO"),
    "zona_secao": _com_digitos((1, 2, 3, 4), "zona ou seção"),
    "categoria_cnh": _categoria_cnh,
    "sexo": _enum(SEXO, "sexo"),
    "estado_civil": _enum(ESTADO_CIVIL, "estado civil"),
    "raca_cor": _enum(RACA_COR, "raça/cor"),
    "tipo_contrato": _enum(TIPO_CONTRATO, "tipo de contrato"),
    "tipo_salario": _enum(TIPO_SALARIO, "tipo de salário"),
    "parentesco": _enum(PARENTESCO, "parentesco"),
    "sim_nao": _enum(SIM_NAO, "sim ou não"),
    "grau_instrucao": _conversor(grau_instrucao, "grau de instrução"),
    "telefone": _telefone,
    "email": _email,
    "dinheiro": _conversor(dinheiro, "valor em reais"),
    "hora": _conversor(hora, "horário"),
    "duracao": _conversor(duracao_minutos, "duração"),
    "inteiro": _conversor(inteiro, "número"),
    "numero": _conversor(numero, "número"),
    "escala": _escala,
}


def normalizar(formato: str, valor) -> tuple:
    """(valor normalizado, None), (None, None) se vazio, ou (None, problema) se não der para usar."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None, None
    return FORMATOS[formato](str(valor))

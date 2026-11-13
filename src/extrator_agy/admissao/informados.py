"""Campos informados à mão por quem confere a ficha (o painel), sem passar pelo agy.

Num complemento, o painel pode mandar, além de arquivos e texto, os valores que
a pessoa digitou ou escolheu num formulário ("estado civil: casado"). Eles são
convertidos e conferidos pelas mesmas regras do texto (regras.FORMATOS) e, na
ficha, valem acima de qualquer documento: o campo recebe o valor, a origem diz
"informado", e os alertas de antes sobre ele (divergente, ausente, inválido)
saem. As conferências de plausibilidade (idade, CEP × UF…) continuam valendo.
"""

import json

from . import regras
from .ficha import INFORMADO, TITULAR
from .schema import CAMPOS_TEXTO

# Caminho na ficha → formato: os campos do funcionário e do contrato que o texto pode citar.
INFORMAVEIS = {caminho: formato for caminho, formato in CAMPOS_TEXTO.items() if caminho in TITULAR}

# Nos enums, o valor do próprio enum também vale (o painel manda "uniao_estavel", não "união estável").
_EXATOS = {
    "sexo": {v for _, v in regras.SEXO},
    "estado_civil": {v for _, v in regras.ESTADO_CIVIL},
    "raca_cor": {v for _, v in regras.RACA_COR},
    "tipo_contrato": {v for _, v in regras.TIPO_CONTRATO},
    "tipo_salario": {v for _, v in regras.TIPO_SALARIO},
    "grau_instrucao": set(regras.GRAUS_INSTRUCAO),
}

ORIGEM = INFORMADO
MAX_CAMPOS = len(INFORMAVEIS)


class CampoInvalido(ValueError):
    """Campo desconhecido ou valor que não converte. A mensagem diz qual campo, nunca o valor."""


def _converter(caminho: str, valor):
    formato = INFORMAVEIS[caminho]
    if formato == "sim_nao" and isinstance(valor, bool):
        return valor
    if isinstance(valor, str) and valor.strip() in _EXATOS.get(formato, ()):
        return valor.strip()
    if not isinstance(valor, (str, int, float)) or isinstance(valor, bool):
        raise CampoInvalido(f"{caminho}: valor em formato inesperado")
    convertido, problema = regras.normalizar(formato, valor)
    if problema:
        raise CampoInvalido(f"{caminho}: {problema}")
    return convertido


def ler(campos: str | None) -> dict:
    """O JSON {caminho: valor} do formulário → {caminho: valor convertido}. Valor vazio é ignorado.

    Levanta CampoInvalido com todos os campos recusados de uma vez (a pessoa corrige tudo junto).
    """
    if not campos or not campos.strip():
        return {}
    try:
        dados = json.loads(campos)
    except ValueError:
        raise CampoInvalido("campos não é um JSON válido") from None
    if not isinstance(dados, dict):
        raise CampoInvalido("campos deve ser um objeto {caminho: valor}")
    if len(dados) > MAX_CAMPOS:
        raise CampoInvalido(f"no máximo {MAX_CAMPOS} campos")
    if desconhecidos := sorted(str(c) for c in dados if c not in INFORMAVEIS):
        raise CampoInvalido(f"campos que não podem ser informados: {', '.join(desconhecidos)}")
    lidos, erros = {}, []
    for caminho, valor in dados.items():
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            continue
        try:
            lidos[caminho] = _converter(caminho, valor)
        except CampoInvalido as e:
            erros.append(str(e))
    if erros:
        raise CampoInvalido("; ".join(erros))
    return lidos

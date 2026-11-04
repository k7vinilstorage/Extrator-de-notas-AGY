"""Números sintéticos com dígito verificador válido, para nenhum número real entrar no repositório."""

from extrator_agy.admissao.regras import _dv_titulo
from extrator_agy.validacao import _dv_pesos


def cpf(base: str = "123456789") -> str:
    dv1 = _dv_pesos(base, list(range(10, 1, -1)))
    dv2 = _dv_pesos(base + str(dv1), list(range(11, 1, -1)))
    c = f"{base}{dv1}{dv2}"
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


def pis(base: str = "1203456789") -> str:
    p = base + str(_dv_pesos(base, [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    return f"{p[:3]}.{p[3:8]}.{p[8:10]}-{p[10]}"


def titulo(sequencial: str = "12345678", uf: str = "09") -> str:
    dv1 = _dv_titulo(sum(int(d) * p for d, p in zip(sequencial, range(2, 10))), uf)
    dv2 = _dv_titulo(int(uf[0]) * 7 + int(uf[1]) * 8 + dv1 * 9, uf)
    return f"{sequencial[:4]} {sequencial[4:]} {uf}{dv1}{dv2}"


def trocar_ultimo(numero: str) -> str:
    """O mesmo número com o último dígito trocado: DV inválido."""
    return numero[:-1] + str((int(numero[-1]) + 1) % 10)

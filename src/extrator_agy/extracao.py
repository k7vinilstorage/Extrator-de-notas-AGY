"""Fluxo completo de extração de uma nota, compartilhado pela CLI e pela API."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .agy import DICA_LOGIN, MODELO_PADRAO, ErroAgy, extrair
from .pdf import renderizar, texto
from .qr import ler_chave_qr
from .schema import NOTA
from .validacao import normalizar, validar

CAMPOS = list(NOTA["properties"])


@dataclass
class Config:
    modelo: str = MODELO_PADRAO
    timeout_s: int = 90
    revisar: bool = True
    limpar_historico: bool = False


@dataclass
class Resultado:
    nota: dict
    problemas: list[str] = field(default_factory=list)
    origem_chave: str = "foto"


def _extrair_com_retentativa(imagens: list[Path], config: Config, **kwargs) -> dict:
    kwargs |= {"modelo": config.modelo, "timeout_s": config.timeout_s, "limpar_historico": config.limpar_historico}
    try:
        return extrair(imagens, **kwargs)
    except ErroAgy as e:
        if str(e).startswith(DICA_LOGIN):
            raise
        # Chamadas do agy às vezes travam ou falham sem motivo; uma nova costuma passar.
        return extrair(imagens, **kwargs)


def _ler(imagens: list[Path], config: Config, chave_qr: str | None, texto_pdf: str | None,
         problemas: list[str] | None = None):
    dados = _extrair_com_retentativa(imagens, config, chave_qr=chave_qr, problemas=problemas)
    if chave_qr:
        dados["chave_acesso"] = chave_qr
    dados = normalizar(dados)
    return dados, validar(dados, texto=texto_pdf)


def processar(arquivo: Path, config: Config) -> Resultado:
    """PDF → imagens e texto → QR code → agy → validação → releitura se a validação falhar.

    Levanta ErroAgy se o agy falhar duas vezes seguidas e PdfInvalido se o PDF não abrir.
    """
    with tempfile.TemporaryDirectory(prefix="extrator-paginas-") as tmp:
        e_pdf = arquivo.suffix.lower() == ".pdf"
        imagens = renderizar(arquivo, Path(tmp)) if e_pdf else [arquivo]
        texto_pdf = texto(arquivo) if e_pdf else None
        chave_qr = next(filter(None, map(ler_chave_qr, imagens)), None)
        dados, problemas = _ler(imagens, config, chave_qr, texto_pdf)
        origem = "QR" if chave_qr else "foto"

        if problemas and config.revisar:
            try:
                novos, novos_problemas = _ler(imagens, config, chave_qr, texto_pdf, problemas)
            except ErroAgy:
                pass
            else:
                if len(novos_problemas) < len(problemas):
                    dados, problemas = novos, novos_problemas
                    origem += ", revisada"

    return Resultado({campo: dados.get(campo) for campo in CAMPOS}, problemas, origem)

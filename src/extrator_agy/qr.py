"""Leitura local do QR code do cupom, que traz a chave de acesso exata."""

import re
from pathlib import Path

import zxingcpp
from PIL import Image, ImageOps

from .validacao import dv_chave


def _decodificar(imagem: Image.Image) -> list[str]:
    return [
        r.text
        for r in zxingcpp.read_barcodes(imagem)
        if r.format == zxingcpp.BarcodeFormat.QRCode
    ]


def ler_chave_qr(arquivo: Path) -> str | None:
    """Retorna a chave de acesso do QR code da foto, ou None se não conseguir ler."""
    if arquivo.suffix.lower() == ".pdf":
        return None
    try:
        imagem = ImageOps.exif_transpose(Image.open(arquivo))
    except OSError:
        return None

    textos = _decodificar(imagem)
    if not textos:
        # QR pequeno na foto: ampliar em tons de cinza costuma resolver.
        cinza = ImageOps.grayscale(imagem)
        textos = _decodificar(cinza.resize((cinza.width * 2, cinza.height * 2)))

    for texto in textos:
        for chave in re.findall(r"\d{44}", texto):
            if dv_chave(chave[:43]) == int(chave[43]):
                return chave
    return None

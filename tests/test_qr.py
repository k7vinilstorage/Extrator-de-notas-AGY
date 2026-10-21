import zxingcpp
from PIL import Image, ImageOps

from extrator_agy.qr import ler_chave_qr
from extrator_agy.validacao import dv_chave

CHAVE_NFCE = "42260204140144000102650020004252171271619150"
CHAVE_NFSE = "53001082247550802000139000000000001124072903992230"


def foto_com_qr(tmp_path, texto):
    qr = zxingcpp.create_barcode(texto, zxingcpp.BarcodeFormat.QRCode).to_image(scale=4)
    altura, largura = qr.shape
    imagem = ImageOps.expand(Image.frombytes("L", (largura, altura), bytes(memoryview(qr))), border=20, fill=255)
    caminho = tmp_path / "cupom.png"
    imagem.save(caminho)
    return caminho


def test_qr_nfce(tmp_path):
    texto = f"https://sat.sef.sc.gov.br/nfce/consulta?p={CHAVE_NFCE}|2|1|1|ABCDEF"
    assert ler_chave_qr(foto_com_qr(tmp_path, texto)) == CHAVE_NFCE


def test_qr_nfse(tmp_path):
    texto = f"https://www.nfse.gov.br/ConsultaPublica?tpc=1&chave={CHAVE_NFSE}"
    assert ler_chave_qr(foto_com_qr(tmp_path, texto)) == CHAVE_NFSE


def test_qr_nfse_nao_vira_chave_de_44(tmp_path):
    # Chave de NFS-e cujos 44 primeiros dígitos também passam no DV da NF-e.
    base = CHAVE_NFSE[:43] + str(dv_chave(CHAVE_NFSE[:43])) + CHAVE_NFSE[44:49]
    chave = base + str(dv_chave(base))
    texto = f"https://www.nfse.gov.br/ConsultaPublica?tpc=1&chave={chave}"
    assert ler_chave_qr(foto_com_qr(tmp_path, texto)) == chave

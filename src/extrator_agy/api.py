"""API HTTP do extrator.

Rodar com um único processo (os lotes ficam em memória):
    uvicorn extrator_agy.api:app --host 0.0.0.0 --port 8000
"""

import asyncio
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import __version__
from .agy import DICA_LOGIN, MODELO_PADRAO, ErroAgy, rodar_agy
from .extracao import Config, processar

EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

TOKEN = os.environ.get("EXTRATOR_API_TOKEN", "")
CONFIG = Config(
    modelo=os.environ.get("EXTRATOR_MODELO", MODELO_PADRAO),
    timeout_s=int(os.environ.get("EXTRATOR_TIMEOUT", "90")),
    revisar=os.environ.get("EXTRATOR_REVISAR", "1") != "0",
    limpar_historico=os.environ.get("EXTRATOR_LIMPAR_HISTORICO", "1") != "0",
)
PARALELO = int(os.environ.get("EXTRATOR_PARALELO", "4"))
MAX_BYTES = int(os.environ.get("EXTRATOR_MAX_MB", "20")) * 1024 * 1024
MAX_ARQUIVOS_LOTE = int(os.environ.get("EXTRATOR_MAX_ARQUIVOS_LOTE", "100"))
LOTE_TTL_S = int(os.environ.get("EXTRATOR_LOTE_TTL_MIN", "60")) * 60

if not TOKEN:
    raise RuntimeError("defina EXTRATOR_API_TOKEN (ex.: openssl rand -hex 32)")

# Fila única para /extrair e /lotes: limita quantos agy rodam ao mesmo tempo.
executor = ThreadPoolExecutor(max_workers=PARALELO, thread_name_prefix="agy")
lotes: dict[str, dict] = {}
trava = threading.Lock()

app = FastAPI(
    title="Extrator de notas - AGY",
    version=__version__,
    description="Extrai CPF/CNPJ, razão social, UF, município, número, data, valor, chave de acesso "
                "e categoria de gasto de notas e cupons fiscais (fotos e PDFs) usando a agy CLI.",
)
bearer = HTTPBearer(auto_error=False)


def autenticar(credenciais: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credenciais is None or not secrets.compare_digest(credenciais.credentials.encode(), TOKEN.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido", {"WWW-Authenticate": "Bearer"})


async def salvar_upload(upload: UploadFile, destino: Path) -> Path:
    """Grava o upload em destino/<nome seguro>, validando extensão e tamanho."""
    sufixo = Path(upload.filename or "").suffix.lower()
    if sufixo not in EXTENSOES:
        raise HTTPException(415, f"{upload.filename}: formato não suportado (use {', '.join(sorted(EXTENSOES))})")
    caminho = destino / f"{uuid.uuid4().hex}{sufixo}"
    tamanho = 0
    with caminho.open("wb") as f:
        while bloco := await upload.read(1024 * 1024):
            tamanho += len(bloco)
            if tamanho > MAX_BYTES:
                raise HTTPException(413, f"{upload.filename}: maior que {MAX_BYTES // 1024 // 1024} MB")
            f.write(bloco)
    if tamanho == 0:
        raise HTTPException(400, f"{upload.filename}: arquivo vazio")
    return caminho


def resposta(nome: str, resultado) -> dict:
    return {
        "arquivo": nome,
        "status": "alerta" if resultado.problemas else "ok",
        "nota": resultado.nota,
        "problemas": resultado.problemas,
        "origem_chave": resultado.origem_chave,
    }


@app.get("/saude", summary="Verifica se a API está no ar (sem autenticação)")
def saude():
    return {"status": "ok", "versao": __version__, "agy_instalado": shutil.which("agy") is not None}


@app.get("/saude/agy", summary="Faz uma chamada real ao agy para confirmar o login", dependencies=[Depends(autenticar)])
def saude_agy():
    try:
        saida = rodar_agy(["--print", "Responda apenas: ok", "--model", CONFIG.modelo],
                          cwd=tempfile.gettempdir(), timeout_s=60, limpar_historico=True)
    except ErroAgy as e:
        raise HTTPException(503, f"agy com erro: {e}") from None
    return {"status": "ok", "modelo": CONFIG.modelo, "duracao_s": saida.get("duration_seconds")}


@app.post("/extrair", summary="Extrai uma nota e espera o resultado", dependencies=[Depends(autenticar)])
async def extrair_nota(arquivo: UploadFile):
    with tempfile.TemporaryDirectory(prefix="extrator-api-") as tmp:
        caminho = await salvar_upload(arquivo, Path(tmp))
        try:
            resultado = await asyncio.wrap_future(executor.submit(processar, caminho, CONFIG))
        except ErroAgy as e:
            codigo = 503 if str(e).startswith(DICA_LOGIN) else 502
            raise HTTPException(codigo, f"falha no agy: {e}") from None
    return resposta(arquivo.filename or caminho.name, resultado)


def _processar_item(lote: dict, i: int, caminho: Path):
    item = lote["resultados"][i]
    item["status"] = "processando"
    try:
        r = resposta(item["arquivo"], processar(caminho, CONFIG))
        item |= {k: r[k] for k in ("status", "nota", "problemas", "origem_chave")}
    except Exception as e:  # registra no item para o lote não ficar travado
        item |= {"status": "erro", "erro": str(e)}
    finally:
        caminho.unlink(missing_ok=True)
        with trava:
            lote["concluidos"] += 1
            if lote["concluidos"] == lote["total"]:
                lote["status"] = "concluido"
                lote["concluido_em"] = time.time()
                shutil.rmtree(lote["_dir"], ignore_errors=True)


def _limpar_lotes_antigos():
    agora = time.time()
    with trava:
        for id_ in [i for i, l in lotes.items() if l.get("concluido_em") and agora - l["concluido_em"] > LOTE_TTL_S]:
            del lotes[id_]


def _publico(lote: dict) -> dict:
    return {k: v for k, v in lote.items() if not k.startswith("_") and k != "concluido_em"}


@app.post("/lotes", status_code=202, summary="Envia várias notas para processar em segundo plano",
          dependencies=[Depends(autenticar)])
async def criar_lote(arquivos: list[UploadFile]):
    if not arquivos:
        raise HTTPException(400, "envie ao menos um arquivo")
    if len(arquivos) > MAX_ARQUIVOS_LOTE:
        raise HTTPException(413, f"no máximo {MAX_ARQUIVOS_LOTE} arquivos por lote")
    _limpar_lotes_antigos()

    diretorio = Path(tempfile.mkdtemp(prefix="extrator-lote-"))
    try:
        caminhos = [await salvar_upload(a, diretorio) for a in arquivos]
    except BaseException:
        shutil.rmtree(diretorio, ignore_errors=True)
        raise

    id_ = uuid.uuid4().hex
    lote = {
        "id": id_,
        "status": "processando",
        "criado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(caminhos),
        "concluidos": 0,
        "resultados": [{"arquivo": a.filename, "status": "pendente"} for a in arquivos],
        "_dir": diretorio,
    }
    with trava:
        lotes[id_] = lote
    for i, caminho in enumerate(caminhos):
        executor.submit(_processar_item, lote, i, caminho)
    return {"id": id_, "total": lote["total"], "url": f"/lotes/{id_}"}


@app.get("/lotes/{id_}", summary="Consulta o andamento e os resultados de um lote", dependencies=[Depends(autenticar)])
def consultar_lote(id_: str):
    _limpar_lotes_antigos()
    lote = lotes.get(id_)
    if lote is None:
        raise HTTPException(404, "lote não encontrado (ou expirado)")
    return _publico(lote)

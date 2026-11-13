"""API HTTP do extrator.

Rodar com um único processo (os lotes ficam em memória):
    uvicorn extrator_agy.api:app --host 0.0.0.0 --port 8000
"""

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import __version__
from .admissao import fluxo as admissao
from .admissao import informados as informados_admissao
from .admissao.schema import TIPOS as TIPOS_DOCUMENTO
from .admissao.docx import DocxInvalido, texto_docx
from .admissao.texto import MAX_CARACTERES, MAX_CARACTERES_TOTAL
from .agy import DADOS_AGY, DICA_LOGIN, MODELO_PADRAO, ErroAgy, consultar_limites, rodar_agy
from .extracao import Config, processar
from .faxina import faxinar
from .pdf import PdfInvalido

EXTENSOES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
# Na admissão chegam também .docx (conta bancária, encaminhamento): viram texto.
EXTENSOES_ADMISSAO = EXTENSOES | {".docx"}

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
MAX_ARQUIVOS_ADMISSAO = int(os.environ.get("EXTRATOR_MAX_ARQUIVOS_ADMISSAO", "30"))
# Menor que o dos lotes: a ficha de admissão é cheia de dado pessoal.
ADMISSAO_TTL_S = int(os.environ.get("EXTRATOR_ADMISSAO_TTL_MIN", "30")) * 60
# Complementos (arquivos e texto acrescentados depois) de uma mesma admissão.
MAX_COMPLEMENTOS = int(os.environ.get("EXTRATOR_MAX_COMPLEMENTOS", "5"))
# Ligada só na imagem Docker: fora dela, os dados do agy são os do usuário.
FAXINA = os.environ.get("EXTRATOR_FAXINA", "0") != "0"

if not TOKEN:
    raise RuntimeError("defina EXTRATOR_API_TOKEN (ex.: openssl rand -hex 32)")

# Fila única para /extrair, /lotes e as admissões: limita quantos agy rodam ao mesmo tempo.
executor = ThreadPoolExecutor(max_workers=PARALELO, thread_name_prefix="agy")
lotes: dict[str, dict] = {}
admissoes: dict[str, dict] = {}
trava = threading.Lock()
# Pastas do /tmp com uploads que ainda vão ser lidos: a faxina não pode apagá-las.
pastas_em_uso: set[Path] = set()

FAXINA_INTERVALO_S = 10 * 60
ultima_faxina = 0.0

# O /usage leva de 3 s a mais de 1 min, então a cota sai do cache e é atualizada em
# segundo plano; só se espera a consulta quando não há resposta boa recente.
LIMITES_CACHE_S = 60
LIMITES_VALIDADE_S = 15 * 60
fila_limites = ThreadPoolExecutor(max_workers=1, thread_name_prefix="limites")
limites: dict = {"dados": None, "em": 0.0, "consulta": None}

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def ao_ligar(_app):
    agendar_faxina()
    atualizar_limites()
    yield


app = FastAPI(
    title="Extrator de notas - AGY",
    version=__version__,
    description="Extrai CPF/CNPJ, razão social, UF, município, número, data, valor, chave de acesso "
                "e categoria de gasto de notas e cupons fiscais (fotos e PDFs) usando a agy CLI. "
                "Também lê os documentos e o texto da admissão de um funcionário (/admissoes).",
    lifespan=ao_ligar,
)
bearer = HTTPBearer(auto_error=False)


def autenticar(credenciais: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credenciais is None or not secrets.compare_digest(credenciais.credentials.encode(), TOKEN.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token inválido", {"WWW-Authenticate": "Bearer"})


async def salvar_upload(upload: UploadFile, destino: Path, extensoes: set[str] = EXTENSOES) -> Path:
    """Grava o upload em destino/<nome seguro>, validando extensão e tamanho."""
    sufixo = Path(upload.filename or "").suffix.lower()
    if sufixo not in extensoes:
        raise HTTPException(415, f"{upload.filename}: formato não suportado (use {', '.join(sorted(extensoes))})")
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


@contextmanager
def em_uso(pasta: Path):
    with trava:
        pastas_em_uso.add(pasta)
    try:
        yield pasta
    finally:
        with trava:
            pastas_em_uso.discard(pasta)


def _faxinar(pastas: set[Path]):
    try:
        apagados = faxinar(Path(tempfile.gettempdir()), DADOS_AGY if CONFIG.limpar_historico else None, pastas)
    except Exception:  # a faxina nunca derruba a API
        log.exception("faxina falhou")
        return
    if any(apagados.values()):
        log.info("faxina: %s", ", ".join(f"{n} {onde}" for onde, n in apagados.items() if n))


def agendar_faxina():
    """Faxina em segundo plano, no máximo uma vez a cada FAXINA_INTERVALO_S."""
    global ultima_faxina
    with trava:
        if not FAXINA or time.time() - ultima_faxina < FAXINA_INTERVALO_S:
            return
        ultima_faxina = time.time()
        pastas = set(pastas_em_uso)
    threading.Thread(target=_faxinar, args=(pastas,), name="faxina", daemon=True).start()


def _consultar_limites():
    dados = consultar_limites()
    with trava:
        limites.update(dados=dados, em=time.time())


def atualizar_limites():
    """Dispara uma consulta da cota se o cache venceu e devolve a consulta em andamento."""
    with trava:
        consulta = limites["consulta"]
        if time.time() - limites["em"] >= LIMITES_CACHE_S and (consulta is None or consulta.done()):
            consulta = limites["consulta"] = fila_limites.submit(_consultar_limites)
        return consulta


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
        saida = rodar_agy(["--print", "Responda apenas: ok", "--model", CONFIG.modelo, "--disable-slash-commands"],
                          cwd=tempfile.gettempdir(), timeout_s=60, limpar_historico=True)
    except ErroAgy as e:
        raise HTTPException(503, f"agy com erro: {e}") from None
    return {"status": "ok", "modelo": CONFIG.modelo, "duracao_s": saida.get("duration_seconds")}


@app.get("/limites", summary="Quanto resta da cota do agy para os modelos Gemini: semanal e de 5 horas",
         dependencies=[Depends(autenticar)])
def ver_limites():
    consulta = atualizar_limites()
    if time.time() - limites["em"] >= LIMITES_VALIDADE_S:
        try:
            consulta.result(timeout=120)
        except ErroAgy as e:
            codigo = 503 if str(e).startswith(DICA_LOGIN) else 502
            raise HTTPException(codigo, f"falha ao consultar a cota no agy: {e}") from None
        except TimeoutError:
            raise HTTPException(504, "o agy não respondeu à consulta da cota") from None
    with trava:
        dados, em = limites["dados"], limites["em"]
    return {"modelo": CONFIG.modelo, **dados,
            "consultado_em": datetime.fromtimestamp(em).astimezone().isoformat(timespec="seconds")}


@app.post("/extrair", summary="Extrai uma nota e espera o resultado", dependencies=[Depends(autenticar)])
async def extrair_nota(arquivo: UploadFile):
    agendar_faxina()
    with tempfile.TemporaryDirectory(prefix="extrator-api-") as tmp, em_uso(Path(tmp)):
        caminho = await salvar_upload(arquivo, Path(tmp))
        try:
            resultado = await asyncio.wrap_future(executor.submit(processar, caminho, CONFIG))
        except ErroAgy as e:
            codigo = 503 if str(e).startswith(DICA_LOGIN) else 502
            raise HTTPException(codigo, f"falha no agy: {e}") from None
        except PdfInvalido as e:
            raise HTTPException(422, f"{arquivo.filename}: {e}") from None
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
                pastas_em_uso.discard(lote["_dir"])
                shutil.rmtree(lote["_dir"], ignore_errors=True)


def _expirar(registro: dict[str, dict], ttl_s: int):
    agora = time.time()
    with trava:
        for id_ in [i for i, r in registro.items() if r.get("concluido_em") and agora - r["concluido_em"] > ttl_s]:
            del registro[id_]


def _limpar_lotes_antigos():
    _expirar(lotes, LOTE_TTL_S)


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
    agendar_faxina()

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
        pastas_em_uso.add(diretorio)
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


# --- Admissão: documentos e texto de um funcionário → ficha com origens e alertas ---

Arquivos = Annotated[list[UploadFile] | None,
                     File(description="Documentos do funcionário (imagens ou PDFs; .docx entra como texto)")]
Texto = Annotated[str | None, Form(description="Informações escritas: cargo, salário, horário etc.")]
Tipos = Annotated[str | None, Form(description='JSON com o tipo de cada arquivo, na mesma ordem, ou null. Ex.: ["rg", null]')]
Campos = Annotated[str | None, Form(description='JSON com os campos informados por quem confere, que valem acima '
                                                'das leituras. Ex.: {"funcionario.estado_civil": "casado"}')]


def _validar_admissao(arquivos: list[UploadFile], texto: str | None, tipos: str | None,
                      com_campos: bool = False) -> tuple[str | None, list]:
    texto = (texto or "").strip() or None
    if not arquivos and not texto and not com_campos:
        raise HTTPException(400, "envie ao menos um arquivo ou o texto")
    if len(arquivos) > MAX_ARQUIVOS_ADMISSAO:
        raise HTTPException(413, f"no máximo {MAX_ARQUIVOS_ADMISSAO} arquivos por admissão")
    if texto and len(texto) > MAX_CARACTERES:
        raise HTTPException(413, f"texto com mais de {MAX_CARACTERES} caracteres")
    try:
        dicas = json.loads(tipos) if tipos else [None] * len(arquivos)
    except ValueError:
        raise HTTPException(400, "tipos não é um JSON válido") from None
    if not isinstance(dicas, list) or len(dicas) != len(arquivos):
        raise HTTPException(400, "tipos deve ser uma lista com um item por arquivo")
    if invalidos := [t for t in dicas if t is not None and t not in TIPOS_DOCUMENTO]:
        raise HTTPException(400, f"tipos desconhecidos: {invalidos} (use {', '.join(TIPOS_DOCUMENTO)})")
    return texto, dicas


async def _receber_admissao(arquivos: list[UploadFile], dicas: list, texto: str | None,
                            destino: Path) -> tuple[list[tuple[Path, str, str | None]], str | None, list[str]]:
    """Grava os documentos e junta ao texto o conteúdo dos .docx (que são apagados em seguida).

    Devolve as entradas das tarefas, o texto completo e os nomes dos .docx.
    """
    entradas, anexos = [], []
    for upload, dica in zip(arquivos, dicas):
        caminho = await salvar_upload(upload, destino, EXTENSOES_ADMISSAO)
        nome = upload.filename or caminho.name
        if caminho.suffix == ".docx":
            try:
                anexos.append((nome, texto_docx(caminho)))
            except DocxInvalido as e:
                raise HTTPException(422, f"{nome}: {e}") from None
            finally:
                caminho.unlink(missing_ok=True)
        else:
            entradas.append((caminho, nome, dica))
    texto = admissao.juntar_texto(texto, anexos)
    if texto and len(texto) > MAX_CARACTERES_TOTAL:
        raise HTTPException(413, f"texto e .docx somam mais de {MAX_CARACTERES_TOTAL} caracteres")
    if not entradas and not texto:
        raise HTTPException(400, "os arquivos enviados não têm conteúdo para ler")
    return entradas, texto, [nome for nome, _ in anexos]


def _finalizar_admissao(adm: dict):
    """Monta a ficha com todas as leituras. Num complemento que não chegou ao fim, a de antes volta."""
    anterior = adm.pop("_anterior", None)
    try:
        if adm["status"] == "processando":
            ficha = admissao.concluir(adm["_resultados"], CONFIG, adm["_informados"])
            # Para um próximo complemento: as leituras que valeram, sem o arquivo (apagado abaixo).
            adm["_resultados"] = [r | {"_caminho": None} for r in ficha.pop("_leituras")]
            adm |= ficha
            adm["status"] = "concluido"
    except Exception as e:  # registra na admissão para ela não ficar travada
        # Só o tipo do erro: a mensagem pode ter dado pessoal lido dos documentos.
        log.error("admissão %s: erro ao montar a ficha (%s)", adm["id"], type(e).__name__)
        adm |= {"status": "erro", "erro": "erro interno ao montar a ficha"}
    finally:
        if anterior is not None and adm["status"] == "erro":
            # O agy perdeu o login no meio, ou a ficha não montou: a admissão continua com a
            # ficha de antes, e o alerta diz que este complemento não entrou.
            motivo = adm.pop("erro", None) or "erro ao ler"
            n = adm["_complementos"]
            adm |= anterior | {"status": "concluido", "resultado": "alerta", "_complementos": n - 1}
            adm["alertas"] = adm["alertas"] + [{
                "campo": None, "tipo": "aviso", "arquivo": None,
                "mensagem": f"o complemento {n} não foi lido ({motivo}); a ficha continua como estava"}]
        elif adm["status"] != "concluido":
            adm["_resultados"] = None
        adm["concluido_em"] = time.time()
        with trava:
            pastas_em_uso.discard(adm["_dir"])
        shutil.rmtree(adm["_dir"], ignore_errors=True)


def _rodar_tarefa_admissao(adm: dict, i: int, tarefa):
    item = adm["documentos"][i]
    if adm["status"] != "processando":  # parou por falta de login ou foi apagada
        resultado = {"status": "erro", "erro": "admissão interrompida"}
    else:
        item["status"] = "processando"
        try:
            resultado = tarefa()
        except admissao.SemLogin as e:
            adm |= {"status": "erro", "erro": f"falha no agy: {e}"}
            resultado = {"status": "erro", "erro": str(e)}
        except Exception as e:
            log.error("admissão %s: erro ao ler o item %d (%s)", adm["id"], i + 1, type(e).__name__)
            resultado = {"status": "erro", "erro": "erro interno"}
    resultado = {**resultado, "arquivo": item["arquivo"]}
    if item.get("complemento"):  # também no erro, que não passa por fluxo.com_complemento
        resultado["complemento"] = item["complemento"]
    adm["_resultados"][i] = resultado
    item |= {k: resultado[k] for k in ("status", "erro") if k in resultado}
    with trava:
        adm["concluidos"] += 1
        ultima = adm["concluidos"] == adm["total"]
    if ultima:
        _finalizar_admissao(adm)


@app.post("/admissoes", status_code=202, dependencies=[Depends(autenticar)],
          summary="Envia os documentos e o texto de um funcionário para ler em segundo plano")
async def criar_admissao(arquivos: Arquivos = None, texto: Texto = None, tipos: Tipos = None):
    arquivos = arquivos or []
    texto, dicas = _validar_admissao(arquivos, texto, tipos)
    _expirar(admissoes, ADMISSAO_TTL_S)
    agendar_faxina()

    diretorio = Path(tempfile.mkdtemp(prefix="extrator-admissao-"))
    try:
        entradas, texto, anexos = await _receber_admissao(arquivos, dicas, texto, diretorio)
    except BaseException:
        shutil.rmtree(diretorio, ignore_errors=True)
        raise

    lista = admissao.tarefas(entradas, texto, CONFIG, anexos)
    id_ = uuid.uuid4().hex
    adm = {
        "id": id_,
        "status": "processando",
        "criado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total": len(lista),
        "concluidos": 0,
        "documentos": [{"arquivo": nome, "status": "pendente"} for _, nome, _ in entradas]
                      + ([{"arquivo": "texto", "status": "pendente"}] if texto else []),
        "complementos": 0,
        "_dir": diretorio,
        "_resultados": [None] * len(lista),
        "_complementos": 0,
        "_informados": {},
    }
    with trava:
        admissoes[id_] = adm
        pastas_em_uso.add(diretorio)
    for i, tarefa in enumerate(lista):
        executor.submit(_rodar_tarefa_admissao, adm, i, tarefa)
    return {"id": id_, "total": adm["total"], "url": f"/admissoes/{id_}"}


# O que volta quando um complemento não chega ao fim (e o que o GET mostra enquanto ele é lido).
_ANTES_DO_COMPLEMENTO = ("documentos", "ficha", "origens", "alertas", "resultado", "total", "concluidos",
                         "complementos", "_resultados", "_informados")


def _reservar_para_complemento(id_: str, conta_no_limite: bool) -> dict:
    """A admissão, já marcada como `processando` (um segundo complemento ao mesmo tempo recebe 409)."""
    with trava:
        adm = admissoes.get(id_)
        if adm is None:
            raise HTTPException(404, "admissão não encontrada (ou expirada, ou apagada)")
        if adm["status"] != "concluido" or adm.get("_resultados") is None:
            motivo = ("ainda está sendo lida: espere terminar" if adm["status"] == "processando"
                      else "não terminou bem: envie de novo")
            raise HTTPException(409, f"a admissão {motivo}")
        if conta_no_limite and adm["_complementos"] >= MAX_COMPLEMENTOS:
            raise HTTPException(409, f"no máximo {MAX_COMPLEMENTOS} complementos por admissão: envie de novo")
        adm["_anterior"] = {k: adm[k] for k in _ANTES_DO_COMPLEMENTO} | {"concluido_em": adm.pop("concluido_em", None)}
        adm["status"] = "processando"
        return adm


def _so_campos(adm: dict, informados: dict) -> dict:
    """Complemento só com campos informados: nada vai ao agy, e a ficha é montada de novo na hora."""
    anterior = adm.pop("_anterior")
    try:
        juntos = adm["_informados"] | informados
        ficha = admissao.concluir(adm["_resultados"], None, juntos)
        ficha.pop("_leituras")  # sem releitura, são as mesmas
    except Exception as e:
        log.error("admissão %s: erro ao montar a ficha com os campos informados (%s)", adm["id"], type(e).__name__)
        with trava:
            adm |= anterior | {"status": "concluido"}
        raise HTTPException(500, "erro interno ao montar a ficha") from None
    with trava:
        adm |= ficha | {"status": "concluido", "_informados": juntos, "concluido_em": time.time()}
    return {"id": adm["id"], "total": adm["total"], "complemento": None, "url": f"/admissoes/{adm['id']}"}


@app.post("/admissoes/{id_}/complemento", status_code=202, dependencies=[Depends(autenticar)],
          summary="Acrescenta arquivos e texto a uma admissão já lida e monta a ficha de novo")
async def complementar_admissao(id_: str, arquivos: Arquivos = None, texto: Texto = None, tipos: Tipos = None,
                                campos: Campos = None):
    """Só o que é novo vai ao agy; a ficha sai da consolidação das leituras de antes e das novas.

    Enquanto o complemento é lido, a admissão volta a `processando`. Se ele não chegar ao fim
    (agy sem login, por exemplo), ela volta à ficha de antes, com um aviso.

    `campos` são valores informados por quem confere a ficha: valem acima das leituras e não
    passam pelo agy. Só com eles (sem arquivo nem texto), a ficha volta pronta na mesma resposta,
    e o envio não conta no limite de complementos.
    """
    arquivos = arquivos or []
    try:
        informados = informados_admissao.ler(campos)
    except informados_admissao.CampoInvalido as e:
        raise HTTPException(400, str(e)) from None
    texto, dicas = _validar_admissao(arquivos, texto, tipos, com_campos=bool(informados))
    _expirar(admissoes, ADMISSAO_TTL_S)
    agendar_faxina()
    if not arquivos and not texto:
        return _so_campos(_reservar_para_complemento(id_, conta_no_limite=False), informados)

    adm = _reservar_para_complemento(id_, conta_no_limite=True)
    with trava:
        n = adm["_complementos"] + 1
        concluido_em = adm["_anterior"].pop("concluido_em")  # lendo, não expira
        adm |= {"_complementos": n, "_informados": adm["_informados"] | informados}

    diretorio = Path(tempfile.mkdtemp(prefix="extrator-admissao-"))
    try:
        entradas, texto, anexos = await _receber_admissao(arquivos, dicas, texto, diretorio)
    except BaseException:
        shutil.rmtree(diretorio, ignore_errors=True)
        with trava:
            adm |= adm.pop("_anterior") | {"status": "concluido", "_complementos": n - 1,
                                           "concluido_em": concluido_em}
        raise

    # O nome diz de qual rodada é o arquivo (e não colide com um de antes, como "print-1.png").
    entradas = [(caminho, f"{nome} (complemento {n})", dica) for caminho, nome, dica in entradas]
    lista = [admissao.com_complemento(t, n) for t in admissao.tarefas(entradas, texto, CONFIG, anexos)]
    novos = [{"arquivo": nome, "status": "pendente", "complemento": n} for _, nome, _ in entradas] \
        + ([{"arquivo": "texto", "status": "pendente", "complemento": n}] if texto else [])
    with trava:
        inicio = len(adm["_resultados"])
        adm |= {"documentos": adm["documentos"] + novos, "_resultados": adm["_resultados"] + [None] * len(lista),
                "total": adm["total"] + len(lista), "complementos": n, "_dir": diretorio}
        pastas_em_uso.add(diretorio)
    for k, tarefa in enumerate(lista):
        executor.submit(_rodar_tarefa_admissao, adm, inicio + k, tarefa)
    return {"id": id_, "total": adm["total"], "complemento": n, "url": f"/admissoes/{id_}"}


@app.get("/admissoes/{id_}", dependencies=[Depends(autenticar)],
         summary="Andamento e, quando concluída, ficha, origens e alertas de uma admissão")
def consultar_admissao(id_: str):
    _expirar(admissoes, ADMISSAO_TTL_S)
    adm = admissoes.get(id_)
    if adm is None:
        raise HTTPException(404, "admissão não encontrada (ou expirada, ou apagada)")
    return _publico(adm)


@app.delete("/admissoes/{id_}", status_code=204, dependencies=[Depends(autenticar)],
            summary="Apaga a admissão da memória (chame assim que tiver guardado a ficha)")
def apagar_admissao(id_: str):
    with trava:
        adm = admissoes.pop(id_, None)
    if adm is None:
        raise HTTPException(404, "admissão não encontrada (ou expirada, ou apagada)")
    if adm["status"] == "processando":
        adm["status"] = "cancelado"  # as tarefas ainda na fila não chamam o agy
    return Response(status_code=204)


@app.post("/admissao", dependencies=[Depends(autenticar)],
          summary="Lê os documentos e o texto de um funcionário e espera a ficha")
async def ler_admissao(arquivos: Arquivos = None, texto: Texto = None, tipos: Tipos = None):
    arquivos = arquivos or []
    texto, dicas = _validar_admissao(arquivos, texto, tipos)
    agendar_faxina()
    with tempfile.TemporaryDirectory(prefix="extrator-admissao-") as tmp, em_uso(Path(tmp)):
        entradas, texto, anexos = await _receber_admissao(arquivos, dicas, texto, Path(tmp))
        lista = admissao.tarefas(entradas, texto, CONFIG, anexos)
        try:
            resultados = await asyncio.gather(*(asyncio.wrap_future(executor.submit(t)) for t in lista))
        except admissao.SemLogin as e:
            raise HTTPException(503, f"falha no agy: {e}") from None
        # Dentro do with: a releitura de documentos divergentes ainda usa os arquivos.
        ficha = await asyncio.to_thread(admissao.concluir, list(resultados), CONFIG)
    ficha.pop("_leituras")
    return {"status": "concluido", **ficha}

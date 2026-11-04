"""Fluxo da admissão: cada arquivo e o texto são uma tarefa; com todas prontas, a ficha.

As tarefas rodam no executor da API, o mesmo de /extrair e /lotes, para que
EXTRATOR_PARALELO limite o total de agy rodando ao mesmo tempo.
"""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from ..agy import DICA_LOGIN, ErroAgy
from ..extracao import Config
from ..pdf import PdfInvalido
from .documentos import ler_arquivo
from .ficha import montar
from .texto import ler_texto


class SemLogin(ErroAgy):
    """O agy está sem login: as outras tarefas falhariam igual, então a admissão para."""


def _erro(nome: str, e: Exception) -> dict:
    if isinstance(e, ErroAgy) and str(e).startswith(DICA_LOGIN):
        raise SemLogin(str(e)) from None
    motivo = f"falha no agy: {e}" if isinstance(e, ErroAgy) else str(e)
    return {"arquivo": nome, "status": "erro", "erro": motivo}


def _ler_arquivo(caminho: Path, nome: str, config: Config, dica_tipo: str | None) -> dict:
    try:
        return ler_arquivo(caminho, nome, config, dica_tipo)
    except (ErroAgy, PdfInvalido) as e:
        return _erro(nome, e)


def _ler_texto(texto: str, config: Config) -> dict:
    try:
        return {"arquivo": "texto", "status": "ok", "fonte": ler_texto(texto, config)}
    except ErroAgy as e:
        return _erro("texto", e)


def tarefas(arquivos: list[tuple[Path, str, str | None]], texto: str | None, config: Config) -> list[Callable[[], dict]]:
    """Uma tarefa por arquivo (caminho, nome original, tipo indicado) e, se houver texto, uma para ele, por último.

    Cada tarefa devolve o item do arquivo, com status ok ou erro; só levanta SemLogin.
    """
    lista = [partial(_ler_arquivo, caminho, nome, config, dica) for caminho, nome, dica in arquivos]
    if texto:
        lista.append(partial(_ler_texto, texto, config))
    return lista


def concluir(resultados: list[dict], com_texto: bool) -> dict:
    """Monta a ficha a partir dos resultados das tarefas, na ordem de `tarefas`."""
    arquivos, texto = (resultados[:-1], resultados[-1]) if com_texto else (resultados, None)
    r = montar(arquivos, texto["fonte"] if texto and texto["status"] == "ok" else None)
    if texto:
        r["documentos"].append({k: texto[k] for k in ("arquivo", "status", "erro") if k in texto})
        if texto["status"] != "ok":
            r["alertas"].append({"campo": None, "tipo": "aviso", "arquivo": "texto",
                                 "mensagem": "o texto não foi lido; os dados dele estão faltando"})
    r["resultado"] = "alerta" if r["alertas"] else "ok"
    return r

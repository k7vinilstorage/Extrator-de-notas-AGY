"""Faxina do que se acumula com o uso: pastas esquecidas no /tmp e restos do agy.

Cada chamada do agy deixa um log (~30 KB), uma linha em conversation_summaries.db,
um arquivo em implicit/ e uma entrada em cache/last_conversations.json (uma por
pasta temporária, que nunca se repete; o agy relê e regrava o arquivo inteiro a
cada chamada). Uma conversa inteira (~1 MB, com a imagem) sobra quando o agy é
morto antes de responder. O agy não apaga nada disso sozinho.
"""

import json
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .agy import apagar_conversa

CONVERSA_MAX_S = 60 * 60
LOG_MAX_S = 7 * 24 * 60 * 60
TMP_MAX_S = 2 * 60 * 60
PREFIXOS_TMP = ("extrator-agy-", "extrator-paginas-", "extrator-lote-", "extrator-api-")


def _velhos(pasta: Path, idade_s: float, agora: float, padrao: str = "*") -> list[Path]:
    try:
        return [c for c in pasta.glob(padrao) if agora - c.stat().st_mtime > idade_s]
    except OSError:
        return []


def _limpar_tmp(tmp: Path, em_uso: set[Path], agora: float) -> int:
    pastas = [p for p in _velhos(tmp, TMP_MAX_S, agora, "extrator-*")
              if p.name.startswith(PREFIXOS_TMP) and p.is_dir() and p not in em_uso]
    for pasta in pastas:
        shutil.rmtree(pasta, ignore_errors=True)
    return len(pastas)


def _limpar_conversas(dados_agy: Path, agora: float) -> int:
    ids = {c.name.split(".")[0] for pasta in ("conversations", "annotations", "presence", "brain")
           for c in _velhos(dados_agy / pasta, CONVERSA_MAX_S, agora)}
    for id_ in ids:
        apagar_conversa(id_, dados_agy)
    return len(ids)


def _limpar_resumos(dados_agy: Path, agora: float) -> int:
    banco = dados_agy / "conversation_summaries.db"
    if not banco.exists():  # connect() criaria um banco vazio
        return 0
    # O agy grava last_modified_time em UTC, como "2026-10-21 18:04:34.49+00:00".
    limite = datetime.fromtimestamp(agora - CONVERSA_MAX_S, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        # O banco está em WAL: dá para apagar com o agy gravando ao mesmo tempo.
        with closing(sqlite3.connect(banco, timeout=10)) as db, db:
            return db.execute("DELETE FROM conversation_summaries WHERE last_modified_time < ?", (limite,)).rowcount
    except sqlite3.Error:
        return 0


def _limpar_ultimas_conversas(dados_agy: Path) -> int:
    arquivo = dados_agy / "cache" / "last_conversations.json"
    try:
        mapa = json.loads(arquivo.read_text())
        vivas = {pasta: conversa for pasta, conversa in mapa.items() if Path(pasta).exists()}
        if len(vivas) == len(mapa):
            return 0
        # Troca atômica: um agy lendo ao mesmo tempo vê o arquivo antigo ou o novo, inteiros.
        novo = arquivo.with_name(f"{arquivo.name}.faxina")
        novo.write_text(json.dumps(vivas, indent=2))
        novo.replace(arquivo)
        return len(mapa) - len(vivas)
    except (OSError, ValueError, AttributeError):
        return 0


def faxinar(tmp: Path, dados_agy: Path | None, em_uso: set[Path] = frozenset()) -> dict[str, int]:
    """Apaga o que passou do prazo e devolve quantos itens saíram de cada lugar.

    `em_uso` são pastas do /tmp que não podem sair (lotes ainda na fila). Com
    `dados_agy` None, os dados do agy ficam intactos: fora do Docker são os do usuário.
    """
    agora = time.time()
    apagados = {"tmp": _limpar_tmp(tmp, em_uso, agora)}
    if dados_agy is None:
        return apagados

    apagados["conversas"] = _limpar_conversas(dados_agy, agora)
    apagados["resumos"] = _limpar_resumos(dados_agy, agora)
    apagados["ultimas_conversas"] = _limpar_ultimas_conversas(dados_agy)
    for nome, pasta, idade_s in (("implicit", "implicit", CONVERSA_MAX_S), ("logs", "log", LOG_MAX_S)):
        arquivos = [a for a in _velhos(dados_agy / pasta, idade_s, agora) if a.is_file()]
        for arquivo in arquivos:
            arquivo.unlink(missing_ok=True)
        apagados[nome] = len(arquivos)
    return apagados

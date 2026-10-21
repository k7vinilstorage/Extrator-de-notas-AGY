"""Chamada da agy CLI em modo não interativo."""

import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .schema import CATEGORIAS, NOTA

MODELO_PADRAO = "Gemini 3.8 Flash (Low)"

PROMPT = """\
Leia {arquivo}, foto ou PDF de um documento fiscal brasileiro, e extraia:
- cpf_cnpj, razao_social, uf, municipio: do EMITENTE (quem vendeu), como impressos.
- numero_nota, data_emissao (ISO 8601, AAAA-MM-DDTHH:MM:SS), valor_total (número, ponto decimal).
- chave_acesso: os 44 dígitos, sem espaços.
- categoria_gasto: {categorias}.
Use null para o que não aparecer ou estiver ilegível; não invente. Só leia o arquivo, nada mais.
"""

DICA_QR = "A chave de acesso, lida do QR code, é {chave}. Use-a.\n"

DICA_REVISAO = """\
Uma leitura anterior deste documento teve estes problemas: {problemas}.
Releia com atenção, dígito por dígito, os campos envolvidos.
"""


DADOS_AGY = Path.home() / ".gemini" / "antigravity-cli"

DICA_LOGIN = "agy sem login; no Docker, rode: docker compose run --rm -it extrator agy"


class ErroAgy(RuntimeError):
    pass


def apagar_conversa(conversation_id: str) -> None:
    """Remove o histórico que o agy grava de cada conversa (~1 MB por nota, com a imagem)."""
    if not re.fullmatch(r"[0-9a-f-]{36}", conversation_id or ""):
        return
    for caminho in (
        DADOS_AGY / "conversations" / f"{conversation_id}.db",
        DADOS_AGY / "annotations" / f"{conversation_id}.pbtxt",
        DADOS_AGY / "presence" / f"{conversation_id}.lock",
    ):
        caminho.unlink(missing_ok=True)
    shutil.rmtree(DADOS_AGY / "brain" / conversation_id, ignore_errors=True)


def rodar_agy(args: list[str], cwd: str, timeout_s: int, limpar_historico: bool = False) -> dict:
    """Roda `agy --output-format json` e devolve o resultado de uma resposta bem-sucedida.

    Sem login, o agy fica até 60 s esperando o código OAuth; aqui o processo é
    encerrado assim que ele pede autenticação.
    """
    if shutil.which("agy") is None:
        raise ErroAgy("agy não encontrado no PATH")

    proc = subprocess.Popen(
        ["agy", *args, "--output-format", "json", "--disable-slash-commands", "--print-timeout", f"{timeout_s}s"],
        cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    sem_login = threading.Event()
    stderr: list[str] = []

    def ler_stderr():
        for linha in proc.stderr:
            stderr.append(linha)
            if "Authentication required" in linha:
                sem_login.set()
                proc.kill()

    estourou = threading.Event()

    def matar_por_timeout():
        estourou.set()
        proc.kill()

    leitor = threading.Thread(target=ler_stderr, daemon=True)
    leitor.start()
    relogio = threading.Timer(timeout_s + 30, matar_por_timeout)
    relogio.start()
    try:
        stdout = proc.stdout.read()
        proc.wait()
        leitor.join(timeout=5)
    finally:
        relogio.cancel()

    if sem_login.is_set():
        raise ErroAgy(DICA_LOGIN)
    if estourou.is_set():
        raise ErroAgy(f"agy não respondeu em {timeout_s}s")
    try:
        saida = json.loads(stdout)
    except json.JSONDecodeError:
        detalhe = ("".join(stderr) or stdout).strip()[-500:]
        raise ErroAgy(f"saída inválida do agy (código {proc.returncode}): {detalhe}") from None

    if limpar_historico:
        apagar_conversa(saida.get("conversation_id", ""))

    if saida.get("status") != "SUCCESS":
        erro = saida.get("error") or f"status {saida.get('status')}"
        if "authentication" in erro.lower() or "sign in" in erro.lower():
            erro = f"{DICA_LOGIN} ({erro})"
        raise ErroAgy(erro)
    return saida


def extrair(
    arquivo: Path,
    modelo: str = MODELO_PADRAO,
    timeout_s: int = 90,
    chave_qr: str | None = None,
    problemas: list[str] | None = None,
    limpar_historico: bool = False,
) -> dict:
    """Extrai os campos de um documento fiscal com o agy.

    O arquivo é copiado para um diretório temporário que vira o único workspace
    do agente, rodando em --mode plan (somente leitura).
    """
    with tempfile.TemporaryDirectory(prefix="extrator-agy-") as tmp:
        copia = Path(tmp) / f"documento{arquivo.suffix.lower()}"
        shutil.copyfile(arquivo, copia)

        prompt = PROMPT.format(arquivo=copia, categorias=", ".join(CATEGORIAS))
        if chave_qr:
            prompt += DICA_QR.format(chave=chave_qr)
        if problemas:
            prompt += DICA_REVISAO.format(problemas="; ".join(problemas))

        saida = rodar_agy(
            ["--print", prompt, "--add-dir", tmp, "--mode", "plan", "--model", modelo,
             "--json-schema", json.dumps(NOTA)],
            cwd=tmp, timeout_s=timeout_s, limpar_historico=limpar_historico,
        )

    if not isinstance(saida.get("structured_output"), dict):
        raise ErroAgy("resposta do agy sem structured_output")
    return saida["structured_output"]

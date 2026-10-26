"""Chamada da agy CLI em modo não interativo."""

import json
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

from .schema import CATEGORIAS, NOTA

MODELO_PADRAO = "Gemini 3.8 Flash (Low)"

PROMPT = """\
Leia {arquivos}: foto ou páginas de um comprovante de gasto no Brasil, seja nota ou cupom fiscal
(NFC-e, NF-e, NFS-e, CF-e SAT) ou recibo sem valor fiscal (corrida de app, por exemplo), e extraia:
- cpf_cnpj, razao_social, uf, municipio: do EMITENTE (quem vendeu ou prestou o serviço), como impressos.
- numero_nota, data_emissao (só a data, sem hora: AAAA-MM-DD), valor_total (número, ponto decimal).
- chave_acesso: os 44 dígitos (50 na NFS-e nacional), sem espaços.
- categoria_gasto: {categorias}.
- itens: só em DANFE de NF-e, cada produto de "Dados dos produtos/serviços" com descricao (o nome
  como impresso, sem as observações abaixo dele) e ncm (Cód. NCM, 8 dígitos); null nos demais documentos.
Use null para o que não aparecer ou estiver ilegível; não invente. Recibos costumam não ter chave
nem número de nota. Só abra as imagens com read_file; não rode comandos.
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


def apagar_conversa(conversation_id: str, dados_agy: Path = DADOS_AGY) -> None:
    """Remove o histórico que o agy grava de cada conversa (~1 MB por nota, com a imagem)."""
    if not re.fullmatch(r"[0-9a-f-]{36}", conversation_id or ""):
        return
    for caminho in (
        dados_agy / "conversations" / f"{conversation_id}.db",
        dados_agy / "annotations" / f"{conversation_id}.pbtxt",
        dados_agy / "presence" / f"{conversation_id}.lock",
    ):
        caminho.unlink(missing_ok=True)
    shutil.rmtree(dados_agy / "brain" / conversation_id, ignore_errors=True)


def rodar_agy(args: list[str], cwd: str, timeout_s: int, limpar_historico: bool = False) -> dict:
    """Roda `agy --output-format json` e devolve o resultado de uma resposta bem-sucedida.

    Sem login, o agy fica até 60 s esperando o código OAuth; aqui o processo é
    encerrado assim que ele pede autenticação.
    """
    if shutil.which("agy") is None:
        raise ErroAgy("agy não encontrado no PATH")

    proc = subprocess.Popen(
        ["agy", *args, "--output-format", "json", "--print-timeout", f"{timeout_s}s"],
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
    # Nesses dois casos o agy sai com status SUCCESS e só avisa no stderr.
    avisos = [linha.strip() for linha in stderr if linha.strip()]
    if any("print timeout" in linha for linha in avisos):
        raise ErroAgy(f"agy não respondeu em {timeout_s}s")
    if not saida.get("response"):
        # Ex.: o agente tentou rodar um comando, que o modo não interativo nega.
        raise ErroAgy(f"agy terminou sem resposta: {(avisos or ['sem detalhes'])[-1][:300]}")
    return saida


def extrair(
    imagens: list[Path],
    modelo: str = MODELO_PADRAO,
    timeout_s: int = 90,
    chave_qr: str | None = None,
    problemas: list[str] | None = None,
    limpar_historico: bool = False,
) -> dict:
    """Extrai os campos de um documento (uma foto ou as páginas de um PDF) com o agy.

    As imagens são copiadas para um diretório temporário que vira o único
    workspace do agente.
    """
    with tempfile.TemporaryDirectory(prefix="extrator-agy-") as tmp:
        copias = []
        for i, imagem in enumerate(imagens, 1):
            nome = f"documento-{i}" if len(imagens) > 1 else "documento"
            copias.append(Path(tmp) / f"{nome}{imagem.suffix.lower()}")
            shutil.copyfile(imagem, copias[-1])

        prompt = PROMPT.format(arquivos=", ".join(map(str, copias)), categorias=", ".join(CATEGORIAS))
        if chave_qr:
            prompt += DICA_QR.format(chave=chave_qr)
        if problemas:
            prompt += DICA_REVISAO.format(problemas="; ".join(problemas))

        saida = rodar_agy(
            ["--print", prompt, "--add-dir", tmp, "--model", modelo, "--json-schema", json.dumps(NOTA),
             "--disable-slash-commands"],
            cwd=tmp, timeout_s=timeout_s, limpar_historico=limpar_historico,
        )

    if not isinstance(saida.get("structured_output"), dict):
        raise ErroAgy("resposta do agy sem structured_output")
    return saida["structured_output"]


# Cotas do grupo de modelos Gemini (Flash e Pro dividem as mesmas) no /usage do agy.
COTAS = {"semanal": "gemini-weekly", "cinco_horas": "gemini-5h"}


def consultar_limites(timeout_s: int = 60) -> dict:
    """Quanto resta das cotas semanal e de 5 horas dos modelos Gemini, e quando renovam.

    O `/usage` não chama o modelo nem gasta cota, mas leva de 3 s a mais de 1 min:
    o serviço de cota às vezes responde 503 e o agy insiste antes de desistir.
    """
    with tempfile.TemporaryDirectory(prefix="extrator-agy-") as tmp:
        # O log fica na pasta temporária: uma consulta por minuto encheria log/.
        saida = rodar_agy(["--print", "/usage", "--log-file", f"{tmp}/agy.log"], cwd=tmp, timeout_s=timeout_s)
    try:
        cotas = {c["id"]: c for g in saida["command"]["data"]["groups"] for c in g["buckets"]}
        return {
            nome: {
                "restante_pct": round(cotas[id_]["remaining_fraction"] * 100, 1),
                "renova_em": datetime.fromisoformat(cotas[id_]["reset_time"]).astimezone().isoformat(timespec="seconds"),
            }
            for nome, id_ in COTAS.items()
        }
    except (KeyError, TypeError, ValueError) as e:
        raise ErroAgy(f"resposta inesperada do /usage do agy ({e!r})") from None

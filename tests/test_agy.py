import json

import pytest

from extrator_agy.agy import ErroAgy, rodar_agy


@pytest.fixture
def agy_falso(tmp_path, monkeypatch):
    """Põe no PATH um `agy` que imprime a saída e o stderr dados."""
    def criar(saida: dict, stderr: str = ""):
        script = tmp_path / "agy"
        script.write_text(f"#!/bin/sh\ncat <<'FIM'\n{json.dumps(saida)}\nFIM\ncat >&2 <<'FIM'\n{stderr}\nFIM\n")
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    return criar


def test_resposta_ok(agy_falso, tmp_path):
    agy_falso({"status": "SUCCESS", "response": "{}", "structured_output": {}})
    assert rodar_agy([], cwd=str(tmp_path), timeout_s=5)["structured_output"] == {}


def test_print_timeout_vira_erro(agy_falso, tmp_path):
    # Estourado o --print-timeout, o agy sai com SUCCESS e resposta vazia.
    agy_falso({"status": "SUCCESS", "response": ""},
              "[agy] print timeout after 90s with turn in progress; returning partial output")
    with pytest.raises(ErroAgy, match="não respondeu em 90s"):
        rodar_agy([], cwd=str(tmp_path), timeout_s=90)


def test_comando_negado_vira_erro(agy_falso, tmp_path):
    agy_falso({"status": "SUCCESS", "response": ""},
              'jetski: no output produced — a tool required the "command" permission that headless mode '
              "cannot prompt for, so it was auto-denied.")
    with pytest.raises(ErroAgy, match="sem resposta: .*command"):
        rodar_agy([], cwd=str(tmp_path), timeout_s=5)

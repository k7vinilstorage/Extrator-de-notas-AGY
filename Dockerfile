FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    # O binário fica em /usr/local/bin, que o usuário app não pode alterar;
    # para atualizar o agy, reconstrua a imagem.
    AGY_CLI_DISABLE_AUTO_UPDATE=1 \
    # Faxina do /tmp e dos restos do agy (veja faxina.py); fora do Docker fica desligada.
    EXTRATOR_FAXINA=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# agy pelo instalador oficial (baixa a versão mais recente e confere o SHA-512)
RUN curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/install.sh \
    && HOME=/tmp/agy-home bash /tmp/install.sh --dir /usr/local/bin \
    && rm -rf /tmp/install.sh /tmp/agy-home \
    && test -x /usr/local/bin/agy

COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# A home inteira é um volume: o login do agy (em ~/.gemini) sobrevive a rebuilds.
RUN useradd --create-home --uid 1000 app
USER app
VOLUME /home/app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/saude')"

# Um único processo: os lotes ficam em memória.
CMD ["uvicorn", "extrator_agy.api:app", "--host", "0.0.0.0", "--port", "8000"]

# Extrator de notas - AGY

Extrai os dados principais de notas e cupons fiscais brasileiros (fotos de cupom NFC-e,
DANFE de NF-e, NFS-e e CF-e SAT, em imagem ou PDF) e de recibos sem valor fiscal, como os de
corrida da Uber e da 99, usando a [agy CLI](https://antigravity.google).
Roda como API HTTP em Docker ou como linha de comando.

Dados extraídos (do emitente):

```json
{
  "cpf_cnpj": "75.315.333/0364-80",
  "razao_social": "ATACADAO S.A.",
  "uf": "SP",
  "municipio": "SAO PAULO",
  "numero_nota": "5340",
  "data_emissao": "2026-06-06",
  "valor_total": 420.78,
  "chave_acesso": "35260675315333036480655120000053401048579176",
  "categoria_gasto": "mercado",
  "itens": null
}
```

Em DANFE de NF-e (exemplo de combustível):

```json
{
  "itens": [
    { "descricao": "DIESEL B S10", "ncm": "27101921" }
  ]
}
```

Campos que não aparecem ou estão ilegíveis vêm como `null`; recibos costumam vir sem
`chave_acesso` e `numero_nota`. `data_emissao` é só a data (`AAAA-MM-DD`), sem hora.
`chave_acesso` tem 44 dígitos (NF-e, NFC-e, CF-e SAT) ou 50 (NFS-e do padrão nacional).
`itens` traz os produtos (`descricao` e `ncm`, com 8 dígitos) de DANFE de NF-e (modelo 55); em
qualquer outro documento (NFC-e, CF-e SAT, NFS-e, recibo) vem `null`.
Categorias possíveis estão em `src/extrator_agy/schema.py`.

## Deploy com Docker

Requer Docker com Compose. O `agy` é instalado dentro da imagem.

```sh
# 1. Configuração: defina ao menos EXTRATOR_API_TOKEN
cp .env.example .env
sed -i "s/^EXTRATOR_API_TOKEN=.*/EXTRATOR_API_TOKEN=$(openssl rand -hex 32)/" .env

# 2. Build
docker compose build

# 3. Login do agy com sua conta Google (só uma vez)
docker compose run --rm -it extrator agy
#    Abra a URL mostrada no navegador, autorize, copie o código exibido e cole no terminal.
#    Depois que o agy abrir, saia com Ctrl+C. O login fica salvo no volume agy-login.

# 4. Subir a API
docker compose up -d

# 5. Conferir se o agy está logado e respondendo
TOKEN=$(grep ^EXTRATOR_API_TOKEN .env | cut -d= -f2)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/saude/agy
```

O login sobrevive a `docker compose down`, rebuilds e restarts; só se perde com
`docker compose down -v` (que apaga o volume). Para trocar de conta, rode o passo 3 de novo e
use `/logout` dentro do agy.

Para atualizar o agy, reconstrua a imagem sem cache: `docker compose build --no-cache`.

### Configuração (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `EXTRATOR_API_TOKEN` | — | Obrigatório. Token exigido em `Authorization: Bearer` |
| `EXTRATOR_PORTA` | `8000` | Porta exposta no host |
| `EXTRATOR_MODELO` | `Gemini 3.8 Flash (Low)` | Modelo do agy (`docker compose run --rm extrator agy models`) |
| `EXTRATOR_PARALELO` | `4` | Chamadas simultâneas ao agy (para `/extrair` e `/lotes` juntos). Cada agy usa ~200 MB de RAM |
| `EXTRATOR_TIMEOUT` | `90` | Segundos por chamada ao agy |
| `EXTRATOR_REVISAR` | `1` | Reler notas que falharem na validação (`0` desliga, mais rápido) |
| `EXTRATOR_MAX_MB` | `20` | Tamanho máximo por arquivo |
| `EXTRATOR_MAX_ARQUIVOS_LOTE` | `100` | Arquivos por lote |
| `EXTRATOR_LOTE_TTL_MIN` | `60` | Minutos que um lote concluído fica disponível |
| `EXTRATOR_LIMPAR_HISTORICO` | `1` | Apaga o histórico que o agy grava de cada conversa (~1 MB por nota) |
| `EXTRATOR_FAXINA` | `1` na imagem | Faxina automática (veja [Faxina](#faxina)). Já vem ligada no Dockerfile |
| `TZ` | `America/Sao_Paulo` | Fuso horário do container |

## API

Documentação interativa em `http://localhost:8000/docs`. Todas as rotas, exceto `/saude`,
exigem `Authorization: Bearer <EXTRATOR_API_TOKEN>`. Formatos aceitos: `.jpg`, `.jpeg`,
`.png`, `.webp`, `.pdf`.

### `POST /extrair`: uma nota, resposta direta (~10–30 s)

```sh
curl -H "Authorization: Bearer $TOKEN" -F "arquivo=@cupom.jpg" http://localhost:8000/extrair
```

```json
{
  "arquivo": "cupom.jpg",
  "status": "ok",
  "nota": { "cpf_cnpj": "...", "razao_social": "...", "...": "..." },
  "problemas": [],
  "origem_chave": "QR"
}
```

`status` é `ok` ou `alerta`; em `alerta`, `problemas` lista o que não bateu na validação
(ex.: dígito verificador da chave inválido). `origem_chave` diz se a chave veio do QR code ou
da leitura da foto.

### `POST /lotes` + `GET /lotes/{id}`: várias notas em segundo plano

```sh
curl -H "Authorization: Bearer $TOKEN" -F "arquivos=@nota1.jpg" -F "arquivos=@nota2.pdf" \
     http://localhost:8000/lotes
# {"id": "3f2a...", "total": 2, "url": "/lotes/3f2a..."}

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/lotes/3f2a...
```

```json
{
  "id": "3f2a...",
  "status": "processando",
  "criado_em": "2026-10-21T11:00:00-03:00",
  "total": 2,
  "concluidos": 1,
  "resultados": [
    { "arquivo": "nota1.jpg", "status": "ok", "nota": { "...": "..." }, "problemas": [], "origem_chave": "QR" },
    { "arquivo": "nota2.pdf", "status": "processando" }
  ]
}
```

Cada resultado passa por `pendente` → `processando` → `ok`, `alerta` ou `erro` (com o campo
`erro`). O lote fica `concluido` quando todos terminam. Os lotes ficam só em memória: somem
após `EXTRATOR_LOTE_TTL_MIN` ou num restart do container.

### `GET /limites`: quanto resta da cota do agy

```sh
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/limites
```

```json
{
  "modelo": "Gemini 3.8 Flash (Low)",
  "semanal": { "restante_pct": 44.7, "renova_em": "2026-10-25T20:49:04-03:00" },
  "cinco_horas": { "restante_pct": 91.5, "renova_em": "2026-10-21T19:01:14-03:00" },
  "consultado_em": "2026-10-21T15:10:00-03:00"
}
```

É a cota que o Gemini Flash (Low) consome: a do grupo de modelos Gemini, que todos os Flash e
Pro dividem, com um limite semanal e um de 5 horas. Vem do `/usage` do agy, que não chama o modelo nem gasta
cota, mas leva de 3 s a mais de 1 min (o serviço de cota do Google às vezes responde 503). Por
isso a resposta sai de um cache e é atualizada em segundo plano a cada minuto em que há
consulta; `consultado_em` diz de quando é. Só a primeira chamada, ou uma depois de 15 min sem
consulta bem-sucedida, espera o agy: use um timeout de cliente de ~2 min.

### Erros

| Código | Quando |
|---|---|
| 401 | Token ausente ou errado |
| 413 | Arquivo grande demais ou lote com arquivos demais |
| 415 | Formato não suportado |
| 422 | PDF ilegível ou protegido por senha |
| 502 | O agy falhou duas vezes seguidas nessa nota, ou não conseguiu consultar a cota |
| 503 | O agy está sem login (rode o passo 3 do deploy) |
| 504 | A consulta da cota não terminou a tempo |

## Linha de comando

Requer o `agy` instalado e autenticado na máquina, e o [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run extrator notas/                  # processa a pasta notas/ e grava em saida/
uv run extrator notas/ -o resultados/   # outra pasta de saída
uv run extrator foto1.jpg foto2.pdf     # arquivos avulsos
uv run extrator notas/ -r -j 8          # inclui subpastas e processa 8 por vez
uv run extrator notas/ --forcar         # reprocessa o que já tem JSON
uv run extrator notas/ --sem-revisao    # não relê notas que falharem na validação
uv run extrator notas/ -m "Gemini 4 Argon (Medium)"   # modelo mais forte para fotos ruins
```

Grava `saida/<arquivo>.json`, um por nota. Notas que já têm JSON no formato atual são puladas.

## Como funciona

1. **PDF** (`pdf.py`): cada página vira um PNG (em PDFs com mais de 4, só as duas primeiras e
   as duas últimas). O texto do PDF, quando existe, é lido para conferir o NCM.
   O agente não lê PDF direto: tenta rodar `pdftotext`, `python` etc., e o agy em modo não
   interativo nega comandos e termina sem resposta. Imagem ele abre com `read_file`.
2. **QR code** (`qr.py`): tenta ler o QR do cupom (na foto ou nas páginas do PDF) localmente.
   Quando consegue, a chave de acesso vem exata dele, sem depender da leitura dos dígitos
   impressos. Na NFS-e o QR é uma URL do portal nacional com a chave de 50 dígitos.
3. **agy** (`agy.py`): as imagens são copiadas para um diretório temporário, que vira o único
   workspace do agente, rodando em modo não interativo (`--print`) com `--json-schema` para
   fixar o formato da resposta. No Docker, sem regras de permissão, o agy nega comandos e o
   agente só consegue ler arquivos. Fora dele vale o `toolPermission` da sua configuração do agy
   (com `always-proceed`, comandos rodam sem perguntar). Chamadas que falham, passam do timeout
   ou terminam sem resposta são repetidas uma vez.
4. **Validação** (`validacao.py`): deixa a data em `AAAA-MM-DD`, confere o dígito
   verificador do CPF/CNPJ e da chave, e se UF, ano/mês, CPF/CNPJ e número embutidos na chave
   batem com o que foi lido. Vale para a chave de 44 posições e para a de 50 da NFS-e nacional
   (município IBGE, ambiente, tipo de inscrição, CPF/CNPJ, número com 13 dígitos, ano/mês,
   código e DV, módulo 11 como na NF-e). Em NF-e, confere se há itens, se cada NCM tem 8 dígitos
   e, quando o PDF tem camada de texto, se o NCM está impresso nele. Se algo falhar, a nota é lida
   de novo uma vez, informando ao modelo os problemas encontrados.

O fluxo fica em `extracao.py`, compartilhado pela API (`api.py`) e pela CLI (`cli.py`).

### Faxina

A cada chamada o agy deixa restos que ele mesmo não apaga: um log (~30 KB), uma linha em
`conversation_summaries.db`, um arquivo em `implicit/` e uma entrada em
`cache/last_conversations.json` (que ele relê e regrava inteiro a cada chamada). Quando o agy é
morto antes de responder, sobra também a conversa inteira (~1 MB). E um restart no meio de um
lote deixa os uploads no `/tmp`.

A API faz uma faxina (`faxina.py`) ao ligar e a cada pedido novo, no máximo uma vez a cada
10 min, em segundo plano. Apaga:

- conversas do agy com mais de 1 hora, e o que sobrou delas nos arquivos acima;
- logs do agy com mais de 7 dias;
- pastas do extrator no `/tmp` com mais de 2 horas que não sejam de um lote ainda na fila.

Os dados do agy só são tocados com `EXTRATOR_LIMPAR_HISTORICO=1`. A faxina vem ligada apenas na
imagem Docker (`EXTRATOR_FAXINA=1`): rodando a API fora dela, apagaria o histórico do seu agy
pessoal.

## Testes

```sh
uv run pytest
```

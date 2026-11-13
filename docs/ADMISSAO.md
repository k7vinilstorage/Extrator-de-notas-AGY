# Extração dos dados de admissão

> **Estado: implementado** (módulo `src/extrator_agy/admissao/`, rotas em `api.py`). As
> diferenças entre a especificação aprovada e o que foi feito estão marcadas no texto.
>
> Escopo desta fase: o Extrator **lê e confere** os documentos e as informações em texto de
> um funcionário e devolve os dados em JSON. Quem estrutura esses dados para o Domínio e gera
> o arquivo de importação é o painel, depois.
>
> Material que havia quando esta especificação foi escrita (04/11/2026): **não havia** a pasta
> `admissao/`, nem ficha modelo nem documentos de exemplo. Havia só a planilha
> `Documentos para admissão.xlsx`, com a lista de documentos pedidos ao funcionário e dos itens
> preenchidos no Domínio, e é nela que se baseiam os campos abaixo.

## Objetivo

O painel manda, de **um** funcionário:

- os **documentos**: vários PDFs e imagens (`.pdf`, `.png`, `.jpg`, `.jpeg`, `.webp`);
- um **texto** curto com o que costuma chegar escrito, sem documento: cargo, salário, data de
  admissão, horário etc. Por exemplo, a mensagem que o cliente mandou.

O extrator devolve:

1. a **ficha** em JSON, com os dados lidos dos documentos e do texto;
2. as **origens**: de qual arquivo, ou do texto, veio cada campo;
3. os **alertas** da validação: dígito verificador, datas, divergências entre fontes e campos
   que faltam.

Uma pessoa sempre revisa a ficha no painel.

O agy só transcreve, tanto dos documentos quanto do texto. Tudo o que dá para conferir é
conferido no código, e o que não aparece ou está ilegível vem `null`. Quando duas fontes
discordam, o código nunca escolhe: o campo fica `null`, com os candidatos no alerta.

## Rotas

Todas exigem `Authorization: Bearer`, como as demais. `/extrair` e `/lotes` não mudam.

| Rota | O que faz | Tempo |
|---|---|---|
| `POST /admissoes` | Recebe arquivos e texto e devolve `202` com o `id` | imediato |
| `GET /admissoes/{id}` | Andamento e, quando terminar, ficha, origens e alertas | imediato |
| `POST /admissoes/{id}/complemento` | Acrescenta arquivos e texto a uma admissão já lida (`202`) | imediato |
| `DELETE /admissoes/{id}` | Apaga a ficha da memória assim que o painel a tiver guardado | imediato |
| `POST /admissao` | Mesmo processamento, mas espera e devolve o resultado | 30 s a 3 min |

**A rota principal é a assíncrona.** Uma admissão tem de 6 a 15 arquivos. Com
`EXTRATOR_PARALELO=4`, cada um levando de 10 a 30 s e a releitura dos que falharem na
validação, ela passa com folga do minuto e meio que proxies e clientes HTTP costumam esperar.
`POST /admissao` existe para testes e admissões pequenas, como `/extrair`.

### Requisição

`multipart/form-data`, igual para `POST /admissoes` e `POST /admissao`:

| Parte | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `arquivos` | arquivo, repetido | sim* | Os documentos (`.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp`, e `.docx`, que entra como texto). Até `EXTRATOR_MAX_ARQUIVOS_ADMISSAO` (padrão 30) |
| `texto` | texto livre | sim* | As informações escritas, como chegaram. Até 10 000 caracteres |
| `tipos` | texto (JSON) | não | Lista na mesma ordem de `arquivos`, com o tipo de cada um ou `null`. Ex.: `["rg", null, "ctps_digital"]` |

\* É preciso mandar ao menos um arquivo ou o texto.

Um `.docx` (dados bancários, encaminhamento admissional) não é lido como imagem: o texto dele vai
junto com o `texto`, depois de uma linha `--- conteúdo do arquivo "nome.docx" ---`, e o arquivo é
apagado logo depois de lido. Na resposta, ele aparece no item `texto`, em `inclui`. O texto
digitado vai até 10 000 caracteres; com os `.docx`, até 30 000.

`tipos` é uma dica, para quando o painel já sabe o que é cada arquivo. Quando o agy discorda
dela, sai um alerta.

```sh
curl -H "Authorization: Bearer $TOKEN" \
     -F "arquivos=@rg-frente.jpg" -F "arquivos=@rg-verso.jpg" -F "arquivos=@ctps.pdf" \
     -F "arquivos=@conta-luz.pdf" -F "arquivos=@certidao-filho.jpg" \
     -F "texto=Admissão da Maria a partir de 10/11/2026, auxiliar administrativo, salário R\$ 2.500,00,
seg a sex 8h às 17h com 1h de almoço, 45 dias de experiência + 45. Quer vale-transporte. Parda, casada." \
     http://localhost:8000/admissoes
# {"id": "8c1e...", "total": 6, "url": "/admissoes/8c1e..."}
```

`total` conta os arquivos mais 1 quando há texto, porque o texto também é uma chamada do agy.

### Complemento

Quando a conferência mostra que faltou um documento ou uma informação (o estado civil, o
comprovante de residência), `POST /admissoes/{id}/complemento`, com as mesmas partes de
`POST /admissoes`, acrescenta o que veio depois, sem mandar tudo de novo:

- só o que é novo vai ao agy. A ficha é montada de novo com as leituras de antes e as novas
  juntas, então quem é quem, as divergências e os alertas saem da mesma consolidação. A
  certidão de um filho mandada depois é ligada à mãe que veio nos documentos de antes, e um
  documento novo que contradiz um de antes vira `divergente`, como se tivessem vindo juntos;
- **no texto, o complemento corrige**: todo campo que ele cita (com trecho, mesmo o que não
  converteu) substitui o do texto de antes, com os problemas dele. O resto do texto de antes
  continua valendo. Dependente citado de novo é o mesmo, pelo nome, e `outras_informacoes`
  se somam;
- os arquivos do complemento ganham o número no nome (`rg.jpg (complemento 1)`), e o
  documento, a origem de cada campo que veio dele e o item `texto` dele trazem
  `"complemento": 1`;
- enquanto o complemento é lido, a admissão volta a `processando` (`total` e `concluidos`
  contam todas as rodadas) e não expira. Se ele não chegar ao fim (o agy sem login, por
  exemplo), ela volta à ficha de antes, com um `aviso` dizendo que o complemento não entrou;
- os arquivos de antes já foram apagados: a releitura do que diverge só relê os novos;
- até `EXTRATOR_MAX_COMPLEMENTOS` (padrão 5) por admissão. `409` quando ela ainda está sendo
  lida, terminou com erro ou passou do limite; `404` quando não existe mais.

**Campos informados** (a partir da 0.8.0): a parte `campos` do complemento é um JSON
`{caminho: valor}` com o que quem confere a ficha digitou ou escolheu num formulário
(`{"funcionario.estado_civil": "casado", "funcionario.endereco.cep": "80010-000"}`). É o caminho
para o que falta sem depender de mais uma leitura:

- vale para os campos do funcionário e do contrato que o texto pode citar
  (`informados.INFORMAVEIS`: `CAMPOS_TEXTO` que estão no `TITULAR`). Os valores passam pelas
  mesmas regras do texto (`regras.FORMATOS`): datas em `DD/MM/AAAA` ou ISO, dinheiro em reais,
  CPF e CEP com ou sem pontuação, e nos enums tanto a palavra ("casada") quanto o valor do enum
  (`uniao_estavel`, `pos_graduacao`). Vazio é ignorado;
- campo desconhecido ou valor que não converte → `400`, com todos os campos recusados de uma
  vez e sem repetir o valor (`funcionario.cpf: CPF com dígito verificador inválido`). Nada muda;
- na ficha, o informado **vale acima de qualquer documento e do texto**: o campo recebe o valor,
  a origem é `[{"arquivo": "painel", "tipo": "informado"}]` e os alertas de antes sobre ele
  (divergente, ausente, inválido) saem; o campo não é relido. As conferências de plausibilidade
  (idade, CEP × UF, término antes da admissão…) continuam valendo para ele;
- o informado continua valendo nos complementos seguintes (o mais novo ganha, campo a campo);
  num complemento que não chega ao fim, os campos dele saem junto;
- **só com `campos`** (sem arquivo nem texto), nada vai ao agy: a ficha é montada de novo na hora
  e já está `concluido` quando a resposta (`202`, com `"complemento": null`) chega. Esse envio não
  conta no limite de complementos.

Para guardar as leituras de um complemento para o próximo, a admissão concluída mantém na
memória, até expirar ou ser apagada, o que foi lido de cada arquivo e do texto (o mesmo dado
pessoal da ficha, campo a campo).

### Resposta de `GET /admissoes/{id}` e `POST /admissao`

```json
{
  "id": "8c1e...",
  "status": "concluido",
  "resultado": "alerta",
  "criado_em": "2026-11-04T10:00:00-03:00",
  "total": 6,
  "concluidos": 6,
  "documentos": [
    { "arquivo": "rg-frente.jpg", "status": "ok", "tipos": ["rg"], "descricoes": ["carteira de identidade, frente"],
      "pessoas": ["titular"], "relido": true },
    { "arquivo": "ctps.pdf", "status": "ok", "tipos": ["ctps_digital"], "descricoes": ["carteira de trabalho digital"],
      "pessoas": ["titular"], "paginas_lidas": [1, 2, 3, 4] },
    { "arquivo": "certidao-filho.jpg", "status": "ok", "tipos": ["certidao_nascimento"],
      "descricoes": ["certidão de nascimento"], "pessoas": ["dependente:1"] },
    { "arquivo": "conta-luz.pdf", "status": "erro", "erro": "falha no agy: agy não respondeu em 90s" },
    { "arquivo": "texto", "status": "ok", "inclui": ["conta bancaria.docx"] }
  ],
  "ficha": {
    "funcionario": { "nome": "MARIA EXEMPLO DA SILVA", "cpf": "123.456.789-09", "raca_cor": "parda", "...": "..." },
    "dependentes": [ { "nome": "JOAO EXEMPLO DA SILVA", "...": "..." } ],
    "contrato": { "data_admissao": "2026-11-10", "cargo": "AUXILIAR ADMINISTRATIVO", "salario": 2500.0, "...": "..." },
    "outras_informacoes": [ "Quer vale-transporte." ]
  },
  "origens": {
    "funcionario.nome": [ { "arquivo": "rg-frente.jpg", "tipo": "rg" }, { "arquivo": "ctps.pdf", "tipo": "ctps_digital" } ],
    "funcionario.raca_cor": [ { "arquivo": "texto", "trecho": "Parda" } ],
    "contrato.salario": [ { "arquivo": "texto", "trecho": "salário R$ 2.500,00" } ]
  },
  "alertas": [
    { "campo": "funcionario.nome_mae", "tipo": "divergente",
      "mensagem": "nome da mãe difere entre RG e certidão de nascimento",
      "candidatos": [ { "valor": "ANA EXEMPLO", "arquivo": "rg-frente.jpg", "tipo": "rg" },
                      { "valor": "ANA EXEMPLO SOUZA", "arquivo": "certidao.jpg", "tipo": "certidao_nascimento" } ] },
    { "campo": "funcionario.endereco", "tipo": "ausente",
      "mensagem": "comprovante de residência não foi lido (conta-luz.pdf com erro)" }
  ]
}
```

- `status` é o andamento: `pendente` → `processando` → `concluido`, como no lote. Cada item de
  `documentos` termina em `ok` ou `erro`.
- `resultado` só aparece quando o `status` é `concluido`: `ok` sem alertas, `alerta` com eles,
  como em `/extrair`.
- `pessoas` diz de quem são os documentos do arquivo: `titular`, `dependente:N` (a ordem em
  `ficha.dependentes`, a partir de 1) ou `nao_identificada`. É uma lista porque um arquivo pode
  ter documentos de mais de uma pessoa. `descricoes` diz o que é cada documento lido, na ordem
  de `tipos`; `relido: true` marca o arquivo relido por divergência com outro documento; no item
  `texto`, `inclui` lista os `.docx` cujo conteúdo foi junto.
- `ficha` tem **só valores**. As origens ficam à parte, para o painel usar a ficha direto.
- `origens` mapeia o caminho do campo para as fontes que o confirmaram. Para o texto, `trecho`
  é a parte do texto de onde o valor saiu, como o agy a citou, para quem revisa encontrar. Um
  campo sem entrada não foi encontrado em lugar nenhum.
- `alertas[].tipo`: `invalido` (dígito verificador ou formato errado mesmo depois da releitura),
  `divergente` (fontes discordam e o campo fica `null`), `ausente` (campo esperado sem valor),
  `aviso` (plausibilidade: comprovante antigo, CNH vencida, titular diferente etc.).
- Um documento com erro (agy falhou duas vezes, PDF ilegível) não derruba a admissão: aparece em
  `documentos` com `erro`, e o que dependia dele cai em `ausente`. A única exceção é o agy sem
  login, que interrompe tudo, porque todos os outros falhariam do mesmo jeito: na rota síncrona,
  com `503`; na assíncrona, com o `status` `erro` e a mensagem.

### Erros

Os códigos existentes continuam valendo. Os novos casos:

| Código | Quando |
|---|---|
| 400 | Nem arquivo nem texto (ou só `.docx` vazios); `tipos` não é JSON válido ou tem tamanho diferente de `arquivos` |
| 404 | Admissão não encontrada, expirada ou apagada |
| 413 | Mais de `EXTRATOR_MAX_ARQUIVOS_ADMISSAO` arquivos, um arquivo maior que `EXTRATOR_MAX_MB`, texto com mais de 10 000 caracteres ou texto e `.docx` somando mais de 30 000 |
| 422 | `.docx` ilegível |
| 415 | Formato não suportado |
| 503 | agy sem login (só na rota síncrona) |

Um PDF ilegível não dá `422` na admissão: ele vira erro só daquele documento.

### Configuração nova (`.env`)

| Variável | Padrão | Descrição |
|---|---|---|
| `EXTRATOR_MAX_ARQUIVOS_ADMISSAO` | `30` | Arquivos por admissão |
| `EXTRATOR_ADMISSAO_TTL_MIN` | `30` | Minutos que uma admissão concluída fica na memória (menos que o lote: tem dado pessoal) |
| `EXTRATOR_MAX_COMPLEMENTOS` | `5` | Complementos por admissão |

O processamento usa o mesmo `executor` de `/extrair` e `/lotes`, então `EXTRATOR_PARALELO`
limita o total.

## Fluxo

```
arquivos ─┬─ PDF → páginas (pdf.py)  ─┐
          └─ imagem                   ├─ agy por arquivo: tipo(s) + transcrição
                                      │     └─ validação do documento → falhou? relê 1 vez
texto ───────────────────────────────── agy: transcrição do texto em campos
                                      │     └─ conversão dos campos (sem releitura)
                                      ↓
              consolidação: quem é quem (titular, dependente), mesclagem, divergências
                                      ↓
                         ficha + origens → validação da ficha → alertas
```

1. **Páginas e fotos.** Uma imagem é uma unidade. Foto com rotação gravada pelo celular (EXIF) é
   endireitada, e foto acima de 6 MP é reduzida, antes de ir ao agy. Um PDF tem as páginas
   renderizadas por `pdf.renderizar`. Na admissão, porém, não dá para ler só as duas primeiras e
   as duas últimas, porque é comum escanear todos os documentos num PDF só: lê até 20 páginas,
   mandando ao agy em grupos de 4 por chamada, e dá um `aviso` se houver mais. Quando o PDF tem
   camada de texto (proposta, contrato, título digital), o texto das páginas vai junto, num `.txt`,
   para o agy conferir letras e números.
2. **Transcrição dos documentos.** Uma chamada do agy por arquivo (ou grupo de 4 páginas). O agy
   diz quais documentos aparecem nas imagens e transcreve cada um. Um arquivo pode conter vários
   documentos (RG e CPF na mesma foto), e um documento pode estar em vários arquivos (frente e
   verso). Veja [Identificação dos documentos](#identificação-dos-documentos).
3. **Transcrição do texto.** Uma chamada à parte, sem imagem e por isso rápida, que roda em
   paralelo com os documentos. Veja [Informações em texto](#informações-em-texto).
4. **Validação por fonte.** Dígitos verificadores, datas e formatos de cada documento e do
   texto. Se algo falhar num documento, o arquivo é lido de novo **uma vez**, com a lista de
   problemas no prompt, e fica a leitura com menos problemas (como em `extracao.processar`).
   O texto não é relido: ele é digital, então o que não converte está escrito assim ("2,5 mil",
   "dia 10") e uma nova leitura não mudaria nada.
5. **Consolidação.** Separa o que é do titular e o que é de cada dependente, junta frente e
   verso, compara o mesmo campo entre fontes e roda a validação da ficha inteira (campos
   esperados, coerência entre datas).
6. **Releitura do que divergiu.** Quando documentos divergem num campo de dígitos ou letras (CPF,
   PIS, nascimento, filiação, RG, título, CEP, CTPS), cada arquivo envolvido é relido uma vez com o
   aviso de quais campos conferir, sem o valor de nenhum dos lados, e a ficha é montada de novo.
   No primeiro teste real, o RG foi lido com o ano de nascimento errado num dígito; a data era
   válida e só a divergência com o CPF e o título mostrou o erro. O nome não é relido: nome
   diferente costuma ser real (de casada, abreviado). O documento relido sai com `relido: true`.

### Identificação dos documentos

O agy recebe um schema com o campo `documentos`, uma lista. Cada item tem `tipo` (enum) e um
objeto por tipo, todos anuláveis: o modelo preenche só o do tipo encontrado. Assim, uma única
chamada classifica e transcreve. O schema é grande, mas os objetos que não se aplicam saem
como `null` e quase não gastam tokens de saída.

Tipos (`tipo`):

| Tipo | Documentos aceitos |
|---|---|
| `rg` | RG estadual (modelos antigo e novo) e CIN (Carteira de Identidade Nacional) |
| `cnh` | CNH física ou digital |
| `cpf` | Cartão do CPF, comprovante de situação cadastral |
| `ctps_digital` | Carteira de Trabalho, digital (tela ou PDF) ou física (o nome do tipo ficou por compatibilidade) |
| `titulo_eleitor` | Título físico ou e-Título |
| `comprovante_residencia` | Qualquer conta, fatura ou boleto com o endereço; contrato de aluguel; declaração de residência |
| `certidao_nascimento` | Certidão de nascimento (do titular ou de dependente) |
| `certidao_casamento` | Certidão de casamento, com ou sem averbação |
| `comprovante_escolaridade` | Diploma, certificado, histórico, declaração de matrícula |
| `comprovante_pis` | Cartão Cidadão, extrato do PIS/FGTS, CNIS |
| `dados_bancarios` | Cartão, extrato, comprovante de conta |
| `contrato_trabalho` | Carta proposta, contrato de trabalho ou de experiência, encaminhamento admissional: preenche o bloco `contrato` |
| `declaracao_vale_transporte` | Declaração de opção pelo vale-transporte: preenche `contrato.vale_transporte` |
| `aso` | Atestado de saúde ocupacional: preenche `contrato.aso` |
| `outro` | Qualquer outra coisa (vira `aviso` com a descrição; o conteúdo não é usado) |

Cada documento vem também com `descricao`, o que ele é em poucas palavras ("carteira de trabalho
física, página de identificação", "foto 3x4, sem documento"), sem nomes nem números. Ela aparece
em `documentos[].descricoes` e no aviso de documento não reconhecido.

**De quem é cada documento.** O titular é o nome que aparece no maior número de documentos de
identificação (`ctps_digital`, `rg`, `cnh`, `cpf`, `titulo_eleitor`), contando como o mesmo nome
as abreviações ("MARIA E. DA SILVA" e "MARIA EXEMPLO DA SILVA") e nomes do meio omitidos. Em
empate, vale o da CTPS. Sem documento de identificação, vale o nome citado no texto. Os outros
documentos se resolvem assim:

- certidão de nascimento cujo registrado é o titular → do titular;
- certidão de nascimento com o titular como pai ou mãe → `dependente:N` (filho);
- certidão de casamento com o titular como um dos cônjuges → do titular, e o outro cônjuge
  entra em `dependentes` com `parentesco: "conjuge"` e `aviso` (quem decide se ele é
  dependente é o painel);
- `rg`, `cpf` ou `cnh` de outra pessoa cujo nome bate com um dependente já identificado → desse
  dependente;
- qualquer outro documento de outra pessoa → `aviso` "documento de pessoa não identificada",
  e o conteúdo fica fora da ficha;
- comprovante de residência em nome de outra pessoa → continua sendo do titular, com `aviso`;
- comprovante de escolaridade, PIS, dados bancários, contrato, declaração de VT e ASO → do
  titular (os quatro últimos com `aviso` se estiverem em nome de outra pessoa);
- documento sem nome legível (manuscrito, foto ruim) e sem CPF ou nascimento de um dependente →
  do titular, com `aviso` para confirmar. No teste real, a CTPS física às vezes vinha sem nome e
  levava junto o PIS.

Os nomes são comparados depois de normalizados: maiúsculas, sem acento, sem espaço duplo e sem
partículas (`DE`, `DA`, `DO`, `DAS`, `DOS`, `E`). O nome normalizado só serve para comparar; a
ficha leva o nome como impresso. Quando o mesmo campo de nome vem abreviado num documento e por
extenso em outro, não é divergência: a ficha leva o mais completo. No primeiro teste real, a CTPS
física abreviava o nome do meio e todos os outros documentos eram descartados como de outra pessoa.

**Fonte repetida ou divergente.** Para cada campo da mesma pessoa:

| Situação | O que acontece |
|---|---|
| Só uma fonte traz o campo | Usa esse valor |
| Várias trazem e, normalizados, são iguais | Usa o valor da fonte de maior precedência; `origens` lista todas |
| Uma traz e outra vem `null` (frente e verso, foto cortada) | Usa o que tem valor |
| Valores diferentes, entre documentos ou entre texto e documento | Campo `null`, alerta `divergente` com todos os candidatos e suas fontes |

Um caso comum de divergência é o **nome de casada**: a CTPS mostra o nome novo e o RG, o
antigo. Quando a certidão de casamento explica a mudança, a mensagem do alerta diz isso, mas o
campo continua `null` até alguém escolher.

A precedência só ordena valores **iguais**, para que `origens` comece pela fonte mais
confiável. Ela nunca desempata valores diferentes.

### Informações em texto

O texto vai para o agy como o arquivo `informacoes.txt`, gravado na pasta temporária que é o
workspace dele, e **não** dentro do prompt. O prompt diz que o arquivo é um dado a transcrever,
não instruções. Isso protege de um texto colado que contenha algo como "ignore as instruções",
e o `--json-schema` limita o que pode sair.

O agy devolve cada campo como **dois** valores: o valor como escrito e o `trecho` do texto de
onde ele saiu. A conversão é feita no código:

| Escrito | No código | Resultado |
|---|---|---|
| `R$ 2.500,00`, `2500`, `2.500`, `2500,00`, `2500.00` | `dinheiro()` | `2500.0` |
| `2,5 mil`, `dois mil e quinhentos`, `piso da categoria` | não converte | `null` + `invalido` com o original |
| `10/11/2026`, `2026-11-10` | `validacao.data_iso` | `"2026-11-10"` |
| `10 de novembro de 2026`, `10/NOV/2026`, `10 / 11 / 2026` | `regras` | `"2026-11-10"` |
| `10/11`, `segunda que vem`, `dia 10` | não converte (falta o ano, ou é relativo) | `null` + `invalido` com o original |
| `45 + 45`, `45 dias prorrogáveis por mais 45` | o agy separa em `dias` e `prorrogacao_dias` | `{dias: 45, prorrogacao_dias: 45}` |
| `8h às 17h, 1h de almoço, seg a sex` | o agy separa entrada, saída, intervalo e dias | `{entrada: "08:00", saida: "17:00", ...}` |

O código nunca completa nem deduz: uma data sem ano não ganha o ano corrente.

O que estiver no texto e não couber em nenhum campo vai para `outras_informacoes` (lista de
trechos como escritos), para não se perder. Exemplos: "começa na filial do centro", "precisa
de uniforme G".

Campos que o texto pode trazer:

- os do bloco [`contrato`](#contrato), que só vêm do texto;
- os de `funcionario` marcados `doc|texto` na tabela, que costumam ser declarados e não aparecem
  em documento: raça/cor, estado civil, telefone, e-mail, grau de instrução, dados bancários,
  deficiência. Se um documento também trouxer o campo e os dois divergirem, sai `divergente`;
- `nome` do funcionário, só para conferir (a ficha usa o dos documentos; se divergir, alerta);
- decisões sobre dependentes ("o filho entra no IR"), ligadas ao dependente pelo nome.

## Schema da ficha

Notação: `str?` é string ou `null`. Datas são `AAAA-MM-DD`, como no resto do serviço. Códigos
com enum (estado civil, raça/cor, grau de instrução) ficam com **nomes legíveis**. A tabela de
cada enum traz o código do eSocial, que o painel pode usar para chegar ao do Domínio.

**Origem**: `doc` vem dos documentos; `texto` vem do texto; `doc|texto` pode vir dos dois e,
se divergirem, sai um alerta; `código` é calculado a partir de outros campos.

**Esperado**: `sim` marca o que o eSocial exige no S-2200 (cadastramento do trabalhador). Um
campo esperado sem valor gera alerta `ausente`, que avisa quem revisa. O que mais o escritório
quer exigir é uma das dúvidas.

### `funcionario`

| Campo | Tipo | Origem (precedência) | Esperado | Validação e normalização |
|---|---|---|---|---|
| `nome` | `str?` | doc: ctps_digital > rg > cnh > cpf > certidao_nascimento | sim | Maiúsculas, espaços simples. Comparado normalizado entre fontes; abreviado e por extenso não divergem (fica o mais completo) |
| `nome_social` | `str?` | texto | não | `null` quando repete o nome civil (formulários costumam repetir) |
| `cpf` | `str?` | doc: cpf > ctps_digital > rg (CIN) > cnh | sim | DV (`validacao.cpf_valido`); formato `000.000.000-00`. Na CIN, o número do RG é o CPF: confere |
| `pis` | `str?` | doc\|texto: comprovante_pis > ctps_digital | não | 11 dígitos, DV módulo 11 com pesos 3,2,9,8,7,6,5,4,3,2; formato `000.00000.00-0` |
| `data_nascimento` | `str?` | doc: certidao_nascimento > rg > cnh > ctps_digital > cpf | sim | Data válida; idade na admissão entre 14 e 100 anos (`invalido` fora disso); de 14 a 15 anos só como aprendiz (`aviso`) |
| `sexo` | `"M"\|"F"\|null` | doc\|texto: certidao_nascimento > rg (CIN) > ctps_digital | sim | Nunca deduzido do nome |
| `nome_mae` | `str?` | doc: certidao_nascimento > rg > cnh > titulo_eleitor | não | Igual a `nome` |
| `nome_pai` | `str?` | doc: igual a `nome_mae` | não | Igual a `nome` |
| `nacionalidade` | `str?` | doc\|texto: rg > ctps_digital; deduzida `"BRASILEIRA"` da certidão de nascimento brasileira | sim | "BRASILEIRO", "Brasil" e "BRASILEIRO(A)" viram `"BRASILEIRA"`; masculino e feminino não divergem |
| `pais_nascimento` | `str?` | doc\|texto: certidao_nascimento > rg | sim | — |
| `municipio_nascimento` | `str?` | doc: certidao_nascimento > rg > cnh | não | Maiúsculas |
| `uf_nascimento` | `str?` | doc: igual ao anterior | não | Uma das 27 UFs |
| `estado_civil` | `enum?` | doc\|texto (veja abaixo) | sim | `solteiro`, `casado`, `divorciado`, `separado`, `viuvo`, `uniao_estavel` |
| `raca_cor` | `enum?` | texto (autodeclaração) | sim | `branca`, `preta`, `parda`, `amarela`, `indigena`, `nao_informado` |
| `grau_instrucao` | `enum?` | doc\|texto: comprovante_escolaridade | sim | Os 12 níveis do eSocial (tabela abaixo) |
| `deficiencia` | `str?` | texto | não | Como escrito; `null` se o texto não falar disso |
| `rg` | `obj?` | doc: rg > cnh (campo "doc. identidade") | não | `{numero, orgao_emissor, uf_emissor, data_expedicao}`; data de expedição ≥ nascimento e ≤ hoje |
| `cnh` | `obj?` | doc: cnh | não | `{numero, categoria, uf_emissor, data_emissao, data_primeira_habilitacao, validade}`; registro com 11 dígitos (o DV não é conferido: há variantes do algoritmo e nenhuma CNH real para confirmar qual vale); `aviso` se vencida; categoria em `A`, `B`, `AB`, `C`, `D`, `E`, `AC`, `AD`, `AE`, `ACC` |
| `ctps` | `obj?` | doc: ctps_digital | não | `{numero, serie, uf}` como impressos. Na CTPS digital o número é o CPF; a conversão para número e série do Domínio fica com o painel |
| `titulo_eleitor` | `obj?` | doc: titulo_eleitor | não | `{numero, zona, secao, uf, municipio, data_emissao}`; 12 dígitos (13 em títulos antigos de SP e MG); DV; UF embutida no número (dígitos 9–10) bate com a UF impressa; zona e seção até 4 dígitos |
| `endereco` | `obj?` | doc\|texto: comprovante_residencia | sim | Veja abaixo |
| `telefone` | `str?` | texto | não | Só dígitos; 10 ou 11 com DDD; DDD válido |
| `email` | `str?` | texto | não | Formato básico `x@y.z` |
| `banco` | `obj?` | doc\|texto: dados_bancarios | não | `{banco, agencia, conta, tipo_conta, pix}` como escritos (o dígito vai junto da conta) |

`endereco`: `{cep, logradouro, numero, complemento, bairro, municipio, uf, titular, data_referencia}`.

- CEP com 8 dígitos e dentro da faixa da UF (tabela de faixas de CEP por UF, no código, sem
  rede). Fora da faixa: `invalido`.
- `numero` vira `"S/N"` só se o documento disser "S/N"; senão fica `null`.
- `titular` e `data_referencia` servem para conferência: `aviso` se o titular não for o
  funcionário ou se a referência tiver mais de 90 dias.

`estado_civil`: em geral vem do texto (é declaração do funcionário). Os documentos servem para
**conferir**:

- certidão de casamento sem averbação → esperado `casado`;
- com averbação de divórcio → `divorciado`; de separação → `separado`; de óbito do cônjuge → `viuvo`;
- só certidão de nascimento, sem anotação de casamento → esperado `solteiro`.

Se o texto não informar, a ficha usa o esperado com `aviso` "estado civil deduzido da
certidão". Se informar algo diferente do esperado, sai `divergente`.

`grau_instrucao`, com o código do eSocial:

| Enum | eSocial | Descrição |
|---|---|---|
| `analfabeto` | 01 | Analfabeto |
| `fundamental_ate_5_incompleto` | 02 | Até o 5º ano incompleto do fundamental |
| `fundamental_5_completo` | 03 | 5º ano completo do fundamental |
| `fundamental_6_a_9_incompleto` | 04 | Do 6º ao 9º ano incompleto |
| `fundamental_completo` | 05 | Fundamental completo |
| `medio_incompleto` | 06 | Médio incompleto |
| `medio_completo` | 07 | Médio completo |
| `superior_incompleto` | 08 | Superior incompleto |
| `superior_completo` | 09 | Superior completo |
| `pos_graduacao` | 10 | Pós-graduação completa |
| `mestrado` | 11 | Mestrado completo |
| `doutorado` | 12 | Doutorado completo |

O agy transcreve o nível e a situação como impressos ou escritos (ex.: "Certificado de conclusão
do Ensino Médio", "terminou o médio"), diz se o documento declara a conclusão (`concluido`) e,
num histórico, qual a última série aprovada. Uma tabela de palavras-chave no código converte para
o enum: "aprovado" sozinho não é conclusão (aparece também em quem só passou de ano), mas a série
final aprovada é (3ª do médio; 9º ano ou 8ª série do fundamental), com `aviso` de que o grau foi
deduzido. O que não der para definir fica `null` com alerta, e um curso livre não define grau.

Raça/cor (eSocial): `branca` 1, `preta` 2, `parda` 3, `amarela` 4, `indigena` 5,
`nao_informado` 6. Estado civil (eSocial): `solteiro` 1, `casado` 2, `divorciado` 3,
`separado` 4, `viuvo` 5; `uniao_estavel` não tem código no eSocial.

### `dependentes` (lista)

| Campo | Tipo | Origem | Esperado | Validação |
|---|---|---|---|---|
| `nome` | `str` | doc: certidao_nascimento > rg > cpf | sim | Como `funcionario.nome` |
| `cpf` | `str?` | doc: cpf > rg (CIN) > certidao_nascimento (modelo com CPF) | não | DV |
| `data_nascimento` | `str?` | doc: certidao_nascimento > rg | sim | Data válida, ≤ hoje; filho ao menos 12 anos mais novo que o titular (`aviso` fora disso) |
| `sexo` | `"M"\|"F"\|null` | doc: certidao_nascimento | não | — |
| `parentesco` | `enum?` | código \| texto | sim | `filho`, `enteado`, `conjuge`, `companheiro`, `outro`. A certidão diz `filho` ou `conjuge`; `enteado` ou `companheiro` só pelo texto |
| `certidao` | `obj?` | doc: certidao_nascimento | não | `{matricula, cartorio, livro, folha, termo, data_registro}`; matrícula com 32 dígitos e tipo de livro (posição 15) que bate com o tipo da certidão; o DV da matrícula não é conferido (falta confirmar o algoritmo com certidões reais) |
| `irrf` | `bool?` | texto | não | `null` se o texto não disser |
| `salario_familia` | `bool?` | texto | não | Idem; `aviso` se `true` e o dependente tiver 14 anos ou mais |

Um dependente citado no texto sem documento correspondente entra com o que o texto traz (nome,
parentesco) e com o `aviso` "dependente sem documento".

### `contrato`

Vem do texto e dos documentos de contrato (carta proposta, contrato de trabalho ou de experiência,
encaminhamento admissional), da declaração de vale-transporte (`vale_transporte`) e do ASO
(`aso`), como escrito, sem códigos do Domínio: o cargo é o nome ("AUXILIAR ADMINISTRATIVO"), não
o código. Quem traduz para o cadastro do Domínio é o painel. Proposta e texto que discordam (de
salário, de horário) viram `divergente`, como entre outros documentos. A lista segue os itens
que a planilha do escritório diz que se preenchem no Domínio.

| Campo | Tipo | Esperado | Validação |
|---|---|---|---|
| `empregador` | `str?` | não | Como escrito (nome comercial e razão social podem divergir) |
| `empregador_cnpj` | `str?` | não | DV do CNPJ; formato `00.000.000/0000-00` |
| `data_admissao` | `str?` | sim | Data completa; de 30 dias atrás a 60 dias à frente (`aviso` fora disso); funcionário com ao menos 14 anos nela |
| `cargo` | `str?` | sim | Maiúsculas |
| `funcao` | `str?` | não | — |
| `cbo` | `str?` | não | 6 dígitos, quando informado |
| `salario` | `number?` | sim | > 0; convertido por `dinheiro()` |
| `tipo_salario` | `enum?` | não | `mensal`, `quinzenal`, `semanal`, `diario`, `horista`, `tarefa`; só se escrito ("por hora" → `horista`) |
| `tipo_contrato` | `enum?` | sim | `indeterminado`, `determinado`, `experiencia` |
| `experiencia` | `obj?` | se `experiencia` | `{dias, prorrogacao_dias}`; total ≤ 90 |
| `data_termino` | `str?` | se `determinado` | > `data_admissao`; no máximo 2 anos depois |
| `horario` | `obj?` | sim | `{entrada, saida, intervalo_inicio, intervalo_fim, intervalo_minutos, dias}`; horas `HH:MM`; saída depois da entrada (ou jornada noturna, com `aviso`). Com mais de um horário (dias úteis e sábado), `entrada` e `saida` são os dos dias úteis e `dias` traz a jornada completa como escrita |
| `escala` | `str?` | não | Ex.: `5x2`, `6x1`, `12x36` |
| `jornada_semanal_horas` | `number?` | não | Só quando escrita (o código não calcula pelo horário); `aviso` acima de 44 |
| `local_trabalho` | `str?` | não | Como escrito |
| `departamento` | `str?` | não | Como escrito |
| `sindicato` | `str?` | não | Como escrito |
| `vale_transporte` | `bool?` | não | `null` se o texto não disser |
| `beneficios` | `list[str]?` | não | Como escritos (VA, VR, plano de saúde) |
| `aso` | `obj?` | não | `{data, apto}`; data ≤ `data_admissao` |
| `primeiro_emprego` | `bool?` | não | — |

## Schema enviado ao agy

Fica em `admissao/schema.py`, no mesmo estilo de `schema.py`: todos os campos obrigatórios e
anuláveis (`STR`), e `additionalProperties: false`. São dois schemas.

```python
# Documentos: um arquivo (ou grupo de páginas) por chamada
DOCUMENTO = {"type": "object", "additionalProperties": False,
             "properties": {"tipo": {"type": "string", "enum": TIPOS},
                            "nome": STR,                       # a pessoa do documento
                            "rg": RG | NULO, "cnh": CNH | NULO, "cpf": CPF | NULO, ...},
             "required": [...]}
DOCUMENTOS = {"type": "object", "additionalProperties": False,
              "properties": {"documentos": {"type": "array", "items": DOCUMENTO}},
              "required": ["documentos"]}

# Texto: cada campo é {valor, trecho}
CITADO = {"type": ["object", "null"], "additionalProperties": False,
          "properties": {"valor": STR, "trecho": STR}, "required": ["valor", "trecho"]}
TEXTO = {"type": "object", "additionalProperties": False,
         "properties": {"nome": CITADO, "cargo": CITADO, "salario": CITADO, ...,
                        "dependentes": {...}, "outras_informacoes": {"type": "array", "items": STR}},
         "required": [...]}
```

`RG | NULO` é o objeto do tipo com `"type": ["object", "null"]`. Os campos de cada documento são
os da coluna `doc` das tabelas acima, como impressos. As datas vêm como impressas (o código
converte com `validacao.data_iso`), e números como CPF, PIS e título vêm com a pontuação
impressa (o código tira).

Os dois prompts pedem, como o atual: transcrever exatamente, usar `null` para o que não aparece
ou está ilegível, não deduzir (por exemplo, não preencher sexo pelo nome), abrir só com
`read_file` e não rodar comandos. Na releitura, a dica lista os problemas **sem os valores**
("CPF com dígito verificador inválido no RG"). Assim nenhum dado lido vai parar no prompt.

**Conferido com o agy 1.5.0** (04/11/2026, dados sintéticos): o `--json-schema` aceita objetos
anuláveis aninhados, e o `read_file` abre o `.txt`. Um texto de exemplo levou 15 s; dois
arquivos de imagem (um com RG e CPF juntos, outro com uma certidão), 28 s. Uma linha "Ignore as
instruções anteriores" no meio do texto foi tratada como dado.

## Dados pessoais (LGPD)

- **Nada em disco além do necessário.** Uploads e `informacoes.txt` vão para
  `tempfile.mkdtemp(prefix="extrator-admissao-")`, apagada ao terminar a admissão. O prefixo
  entra em `faxina.PREFIXOS_TMP`, e a pasta fica em `pastas_em_uso` enquanto houver algo na
  fila, como nos lotes.
- **Na memória, só pelo tempo necessário.** A admissão concluída fica em memória por
  `EXTRATOR_ADMISSAO_TTL_MIN` (padrão 30), contados do fim da última leitura (um
  complemento recomeça a conta). Junto com a ficha ficam as leituras de cada arquivo e do
  texto, para um complemento montar a ficha de novo. O painel deve chamar `DELETE /admissoes/{id}`
  assim que guardar a ficha. Um restart apaga tudo.
- **Logs.** Nenhum log do extrator inclui valor de campo, o texto, o nome de arquivo enviado
  (costuma ter o nome da pessoa: `rg maria.jpg`) ou mensagem de alerta. Só se registram o id da
  admissão, contagens e tipos de documento. Os erros do agy podem conter trechos da resposta do
  modelo (`saída inválida do agy ... {detalhe}`). Eles vão para a resposta HTTP (o painel é
  autorizado), mas nunca para o log.
- **Restos do agy.** As chamadas de admissão usam `--log-file` dentro da pasta temporária (o
  mesmo truque de `consultar_limites`): o log do agy, que pode conter o prompt, some com a pasta,
  em vez de ficar 7 dias em `log/`. A conversa é apagada logo depois (`limpar_historico`), e a
  faxina cobre o que sobrar.
- **Prompt sem dados.** O texto vai num arquivo, não no prompt, e a releitura informa o problema
  sem o valor lido.
- **Fixtures.** Os testes usam só dados sintéticos: CPF, PIS e título gerados no próprio teste
  com DV válido, e documentos sintéticos (espécimes oficiais com dados fictícios) em
  `tests/admissao/sinteticos/`, que vão para o git. Documentos anonimizados reais, para testar à
  mão, ficam em `admissao/`, que o git ignora (como `notas/`).
- **Terceiro.** Os documentos e o texto vão para o modelo do Google pelo agy, como as notas.
  Isso já foi decidido, mas deve constar no registro de tratamento do escritório.

## Módulos

Subpacote `src/extrator_agy/admissao/`, separado do que é de notas. Funções curtas, type hints e
nenhuma classe além do estado interno da consolidação.

| Arquivo | Conteúdo |
|---|---|
| `agy.py` (alterado) | `transcrever(arquivos, prompt, schema, ..., log_temporario)`: a parte genérica de `extrair`, que continua igual |
| `pdf.py` (alterado) | `contar_paginas` e `renderizar(..., indices=None)`; sem `indices`, o comportamento de antes |
| `faxina.py` (alterado) | `"extrator-admissao-"` em `PREFIXOS_TMP` |
| `admissao/schema.py` | Campos e formato de cada tipo de documento e do texto; schemas `DOCUMENTOS` e `TEXTO` |
| `admissao/regras.py` | Validações e conversões puras: DV do PIS e do título, faixa de CEP por UF, DDD, idade, nome para comparar, dinheiro, hora, duração, palavras-chave dos enums. Reaproveita `validacao.cpf_valido`, `digitos`, `data_iso` e `_dv_pesos` |
| `admissao/documentos.py` | Prompt e chamada do agy para um arquivo (grupos de 4 páginas), normalização e conferência por documento, releitura |
| `admissao/texto.py` | Prompt e chamada do agy para o texto (em `informacoes.txt`), conversão dos campos |
| `admissao/ficha.py` | Consolidação: titular × dependentes, mesclagem, divergências, precedência, origens e conferências da ficha inteira |
| `admissao/fluxo.py` | Uma tarefa por arquivo e uma para o texto, que a API roda no executor; `concluir` monta a ficha; `com_complemento` e `mesclar_textos` para os complementos |
| `admissao/informados.py` | Os campos informados no painel (`campos` do complemento): quais podem ser informados e a conversão pelas regras do texto |
| `api.py` (alterado) | Rotas `/admissoes`, `/admissoes/{id}/complemento` e `/admissao` |

Formato de uma fonte, que liga `documentos.py` e `texto.py` a `ficha.py`:

```python
{"arquivo": "rg-frente.jpg", "tipo": "rg", "campos": {"nome": "MARIA ...", ...},
 "problemas": [{"campo": "cpf", "mensagem": "...", "valor": "..."}], "avisos": [...]}
# o texto tem também "trechos", "dependentes" e "outras_informacoes", e campos pelo caminho na ficha
```

## Plano de testes

`uv run pytest -q`, sem rede e sem agy. O agy é sempre trocado por monkeypatch: em
`documentos.py` e `texto.py`, `agy.transcrever` devolve um `structured_output` fixo.

| Arquivo | O que cobre |
|---|---|
| `tests/test_agy.py` (+) | `transcrever` com um agy falso que anota os argumentos; `extrair` continua igual |
| `tests/test_pdf.py` (+) | `renderizar(indices=...)` e `contar_paginas`; o padrão continua igual |
| `tests/admissao/test_regras.py` | DV de PIS e título (12 e 13 dígitos, SP/MG), com números **gerados** e casos de erro (um dígito trocado, todos iguais); CEP × UF nas bordas das faixas; normalização de nome (acentos, partículas); palavras-chave de grau de instrução, estado civil e raça/cor |
| `tests/admissao/test_documentos.py` | agy falso → documento normalizado; data `DD/MM/AAAA`; releitura quando o DV falha, ficando a leitura com menos problemas; prompt de releitura **sem** o valor lido; PDF com 10 páginas → 2 chamadas e `aviso`; erro do agy duas vezes → documento com erro |
| `tests/admissao/test_texto.py` | `dinheiro()` em todos os formatos da tabela; data sem ano → `null` + `invalido`, nunca o ano corrente; horário e experiência; o texto vai no arquivo `informacoes.txt` e **não** no prompt; trecho fora dos campos → `outras_informacoes`; sem releitura |
| `tests/admissao/test_ficha.py` | Titular pela CTPS e pela maioria; certidão de filho → dependente; cônjuge pela certidão de casamento; frente e verso se completando; nome divergente RG × CTPS → `null` + `divergente` com os dois candidatos; nome de casada com certidão; texto × documento divergente; estado civil deduzido e conflitante; dependente só no texto; esperados `ausente`; idade fora da faixa; `origens` com `trecho` |
| `tests/admissao/test_api_admissao.py` | Rotas com a leitura falsa e a ficha de verdade: 401, 400 (nem arquivo nem texto), 413 (arquivos e texto), 415; só texto, sem arquivo; assíncrona até `concluido`; `DELETE`; TTL; pasta temporária apagada e fora de `pastas_em_uso` no fim; agy sem login (503 e `erro`); **nenhum log com CPF, nome ou texto** (`caplog`) |

Fixtures: dicionários Python nos próprios testes, no formato do `structured_output` do agy. CPF,
PIS e título são gerados por `tests/admissao/numeros.py`, que calcula o DV, de modo que nenhum
número real entra no repositório.

`tests/admissao/test_real.py` roda o agy de verdade sobre `tests/admissao/sinteticos/`: espécimes
oficiais (CIN do Serpro e certidões do Provimento CNJ 182/2024) preenchidos com dados fictícios,
mais um texto de exemplo. Ele gasta cota e leva cerca de 40 s, então só roda com
`EXTRATOR_TESTE_AGY=1`. Foi esse teste que mostrou que a CIN imprime datas como
`05 / 03 / 1990` e que o texto pode trazer "mais 60" na prorrogação.

## Fora desta fase

- **Arquivo de importação do Domínio**: fica com o painel, a partir desta ficha. Os enums já
  trazem o código do eSocial para facilitar o mapeamento.
- Ler o QR code da CIN, da CNH digital ou do e-Título com `qr.py`. Não sei se o conteúdo é
  legível (o da CNH digital é assinado); dá para investigar depois, com documentos reais.
- Subcomando na CLI (`extrator admissao pasta/ --texto info.txt`). É útil para testar com o agy
  local, mas não foi pedido.
- Consultar CEP ou município em serviço externo (a faixa de CEP por UF é local).

## Dúvidas

1. **Exemplos de texto.** Pode mandar 3 ou 4 textos reais (anonimizados) de como as informações
   chegam? Mensagem de WhatsApp, e-mail, lista? Com eles eu ajusto os campos do `contrato` e as
   conversões.
2. **O texto pode trazer dado pessoal** (estado civil, raça, telefone, banco)? Assumi que sim.
   Também pode falar de mais de um funcionário? Assumi que não: uma admissão é de uma pessoa.
3. **Campos esperados.** A coluna "Esperado" segue o eSocial. O escritório quer alerta `ausente`
   também para PIS, RG, título, nome da mãe, CPF dos dependentes ou ASO?
4. **`tipos`.** O painel sabe o que é cada arquivo? Se não souber, a dica pode sair da
   especificação.
5. **Rotas.** `POST /admissoes` (assíncrona) e `POST /admissao` (síncrona). Os nomes estão bons?
   Precisa mesmo da síncrona?
6. **Fixtures anonimizadas.** Ao trocar os números, use CPF, PIS e título **com DV válido**,
   senão o teste real vai acusar `invalido` em tudo; posso gerar uma lista. As imagens (com foto
   de rosto, mesmo anonimizadas) devem ficar fora do git, em `admissao/` ignorada como `notas/`?
   Recomendo que sim.

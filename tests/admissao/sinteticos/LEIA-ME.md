# Documentos sintéticos para testar a leitura da admissão

Nenhum dado aqui é de pessoa real. Os documentos são **espécimes oficiais** preenchidos com dados
fictícios (CPFs gerados com DV válido por `tests/admissao/numeros.py`):

| Arquivo | Espécime de origem |
|---|---|
| `cin-fulana.png` | Modelo em papel da CIN (frente e verso, campos "NONONONO" e silhueta), publicado pelo Serpro em [nova-carteira-de-identidade-comeca-a-ser-emitida-no-brasil](https://www.serpro.gov.br/menu/noticias/noticias-2022/nova-carteira-de-identidade-comeca-a-ser-emitida-no-brasil) |
| `certidoes.pdf` | Anexos V (casamento) e IV (nascimento) do [Provimento CNJ 182/2024](https://arpenbrasil.org.br/wp-content/uploads/2024/09/cnj-prov-182.pdf), páginas 7 e 6 |
| `texto.txt` | Mensagem de admissão escrita para o teste |

A família fictícia: Fulana Teste de Souza (titular, CPF 123.456.789-09, nascida em 05/03/1990),
casada com Fulano de Tal Souza (CPF 111.444.777-35), mãe de Ciclano Teste de Souza
(CPF 987.654.321-00, nascido em 01/02/2015).

`preencher.py` refaz as imagens a partir dos originais baixados (`cin-papel.jpg` do Serpro e o PDF
do provimento): `python preencher.py <pasta dos originais> <pasta de saída>`. O PDF de 2 páginas é
montado juntando as duas certidões.

Teste com o agy de verdade (gasta cota; leva cerca de 1 min):

    EXTRATOR_TESTE_AGY=1 uv run pytest tests/admissao/test_real.py -v

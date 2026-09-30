# Médias dos benchmarks

10 rodadas por cenário, 90 execuções verificadas e 90,000 operações medidas. Cada execução usa 1000 registros, 1000 operações, 8 threads e atraso assíncrono de 1.0 s. A primeira rodada foi preservada e entrou nas médias.

| Modo | Leitura: média ± DP (ops/s) | Escrita: média ± DP (ops/s) | Misto: média ± DP (ops/s) | Erros totais |
| --- | --- | --- | --- | --- |
| strong | 41,79 ± 7,20 | 7,87 ± 1,46 | 12,46 ± 1,46 | 30 |
| eventual | 498,35 ± 103,50 | 21,22 ± 3,89 | 40,50 ± 3,97 | 56 |
| ryw | 383,85 ± 101,94 | 19,96 ± 3,62 | 43,58 ± 8,48 | 36 |

## Detalhamento por cenário

| Carga | Modo | N | Média (ops/s) | DP (ops/s) | Tempo médio (s) | Leitura média (ms) | Média p95 leitura (ms) | Escrita média (ms) | Média p95 escrita (ms) | Erros totais | Erros (%) | Convergência média (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| leitura | strong | 10 | 41,79 | 7,20 | 24,72 | 196,90 | 275,67 | — | — | 10 | 0,10 | 0,01 |
| leitura | eventual | 10 | 498,35 | 103,50 | 2,17 | 16,31 | 34,39 | — | — | 45 | 0,45 | 0,01 |
| leitura | ryw | 10 | 383,85 | 101,94 | 2,79 | 18,27 | 34,85 | — | — | 23 | 0,23 | 0,01 |
| escrita | strong | 10 | 7,87 | 1,46 | 132,38 | — | — | 1052,94 | 1603,38 | 20 | 0,20 | 0,13 |
| escrita | eventual | 10 | 21,22 | 3,89 | 48,34 | — | — | 385,44 | 639,44 | 11 | 0,11 | 26,72 |
| escrita | ryw | 10 | 19,96 | 3,62 | 51,43 | — | — | 409,94 | 683,21 | 12 | 0,12 | 23,22 |
| misto | strong | 10 | 12,46 | 1,46 | 81,36 | 623,18 | 1002,90 | 674,19 | 1082,62 | 0 | 0,00 | 0,02 |
| misto | eventual | 10 | 40,50 | 3,97 | 24,90 | 52,17 | 130,96 | 325,39 | 606,39 | 0 | 0,00 | 17,71 |
| misto | ryw | 10 | 43,58 | 8,48 | 23,62 | 45,09 | 112,70 | 316,35 | 593,69 | 1 | 0,01 | 15,57 |

## Como interpretar

- Cada média é aritmética, com o mesmo peso para cada rodada. DP é o desvio-padrão amostral (divisor N − 1).
- As latências são médias das métricas de operações bem-sucedidas de cada rodada. A média dos p95 não é o p95 combinado de todas as operações.
- O throughput do YCSB inclui tentativas que falharam. Erros são somados, sem excluir rodadas com falhas; o JSON também fornece a média de erros por rodada.
- A espera pela convergência é medida após o YCSB e não entra no throughput. Todas as réplicas convergiram em todas as execuções incluídas.
- A base inicial é idêntica para todos os casos; processos são recriados, sem aquecimento dedicado, e a ordem dos modos alterna entre rodadas. Carga mista: 50% de probabilidade para cada operação, com contagens efetivas aleatórias.
- Medições locais feitas em sessões diferentes; as datas estão registradas em results.json. A variação do computador pode influenciar os resultados; as médias não demonstram as garantias de consistência.
- medias.json inclui média, desvio-padrão, mínimo, máximo e N de cada métrica. Também inclui operações totais divididas pelo tempo total (pooled_ops_sec), que difere da média aritmética de ops/s.

[Resultados individuais](comparacao.md) · [Médias em JSON](medias.json)

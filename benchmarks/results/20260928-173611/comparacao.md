# Comparacao dos modos de consistencia

1000 registros; 1000 operacoes por execucao; 8 threads; 1 rodada(s); atraso assincrono de 1.0 s. Escrita = UPDATE; misto = 50% READ / 50% UPDATE (sorteio por operacao). Um campo de 100 caracteres, distribuicao uniforme. Carga inicial via YCSB em strong com 1 thread e ate 5 retries por registro, fora da medicao. Cada caso usa uma copia identica dessa base, novos processos e portas locais livres. Execucoes sequenciais, sem aquecimento dedicado, com logs em arquivos. Throughput e latencia sao os do cliente YCSB; a espera posterior pela convergencia nao entra no tempo medido. Latencias exibidas em milissegundos (YCSB exporta microssegundos). A convergencia compara todos os valores e versoes persistidos; nao comprova, por si so, as garantias de consistencia. Resultados locais exploratorios, sujeitos a variacao de carga do computador; nao ha intervalo de confianca com uma unica rodada.

| Carga | Modo | Rodada | Ops/s | Tempo (s) | Leitura media (ms) | Leitura p95 (ms) | Escrita media (ms) | Escrita p95 (ms) | OK | Erros | Espera convergencia (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| leitura | strong | 1 | 28.16 | 35.51 | 282.53 | 389.89 | — | — | 1000 | 0 | 0.00 |
| leitura | eventual | 1 | 214.27 | 4.67 | 33.95 | 86.21 | — | — | 998 | 2 | 0.05 |
| leitura | ryw | 1 | 218.87 | 4.57 | 30.39 | 61.53 | — | — | 998 | 2 | 0.01 |
| escrita | strong | 1 | 4.64 | 215.31 | — | — | 1692.35 | 3606.53 | 986 | 14 | 0.23 |
| escrita | eventual | 1 | 20.95 | 47.73 | — | — | 380.01 | 498.18 | 1000 | 0 | 28.61 |
| escrita | ryw | 1 | 24.36 | 41.05 | — | — | 327.59 | 497.66 | 998 | 2 | 22.06 |
| misto | strong | 1 | 9.45 | 105.86 | 778.98 | 1297.41 | 909.73 | 1422.34 | 1000 | 0 | 0.01 |
| misto | eventual | 1 | 38.98 | 25.65 | 50.91 | 101.69 | 334.16 | 459.52 | 1000 | 0 | 19.29 |
| misto | ryw | 1 | 39.56 | 25.28 | 43.57 | 106.81 | 342.43 | 513.28 | 1000 | 0 | 16.24 |

Ambiente: Windows-11-10.0.26200-SP0; Python 3.13.7 (tags/v3.13.7:bcee1c3, Aug 14 2025, 14:15:11) [MSC v.1944 64 bit (AMD64)]; Java: java version "21.0.7" 2025-04-15 LTS

Os comandos exatos, logs e metricas brutas ficam nas pastas de cada caso. results.json contem parametros, hashes dos fontes e todos os resultados.

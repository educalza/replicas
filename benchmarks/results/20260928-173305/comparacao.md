# Comparacao dos modos de consistencia

1000 registros; 10000 operacoes por execucao; 8 threads; 1 rodada(s); atraso assincrono de 1.0 s. Escrita = UPDATE; misto = 50% READ / 50% UPDATE (sorteio por operacao). Um campo de 100 caracteres, distribuicao uniforme. Carga inicial via YCSB em strong, fora da medicao. Cada caso usa uma copia identica dessa base, novos processos e portas locais livres. Execucoes sequenciais, sem aquecimento dedicado, com logs em arquivos. Throughput e latencia sao os do cliente YCSB; a espera posterior pela convergencia nao entra no tempo medido. Latencias exibidas em milissegundos (YCSB exporta microssegundos). A convergencia compara todos os valores e versoes persistidos; nao comprova, por si so, as garantias de consistencia. Resultados locais exploratorios, sujeitos a variacao de carga do computador; nao ha intervalo de confianca com uma unica rodada.

| Carga | Modo | Rodada | Ops/s | Tempo (s) | Leitura media (ms) | Leitura p95 (ms) | Escrita media (ms) | Escrita p95 (ms) | OK | Erros | Espera convergencia (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Ambiente: Windows-11-10.0.26200-SP0; Python 3.12.14 (main, Aug 25 2026, 14:01:42) [MSC v.1944 64 bit (AMD64)]; Java: java version "21.0.7" 2025-04-15 LTS

Os comandos exatos, logs e metricas brutas ficam nas pastas de cada caso. results.json contem parametros, hashes dos fontes e todos os resultados.

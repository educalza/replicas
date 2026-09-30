# Benchmarks comparativos

O script `run_benchmarks.py` executa o YCSB nos modos `strong`, `eventual` e
`ryw`, para leitura, escrita (UPDATE) e carga mista (50% de cada).
Ele cria processos, portas locais e arquivos de dados exclusivos para cada
caso, sem alterar os arquivos da pasta `data` nem utilizar servidores ja abertos.

## Comparacao executada

Resultado final com 10 rodadas por cenário, 1.000 registros, 1.000 operações
por caso, 8 threads e atraso de propagação de 1 segundo:

| Modo | Leitura: média ± DP (ops/s) | Escrita: média ± DP (ops/s) | Misto: média ± DP (ops/s) | Erros nas 30.000 operações |
| --- | ---: | ---: | ---: | ---: |
| strong | 41,79 ± 7,20 | 7,87 ± 1,46 | 12,46 ± 1,46 | 30 |
| eventual | 498,35 ± 103,50 | 21,22 ± 3,89 | 40,50 ± 3,97 | 56 |
| ryw | 383,85 ± 101,94 | 19,96 ± 3,62 | 43,58 ± 8,48 | 36 |

[Tabela final de médias em HTML](results/20260928-173611/medias.html),
[tabela de médias em Markdown](results/20260928-173611/medias.md),
[médias e estatísticas em JSON](results/20260928-173611/medias.json),
[resultados individuais](results/20260928-173611/comparacao.html) e
[métricas brutas e parâmetros](results/20260928-173611/results.json).

Todas as réplicas convergiram após as 90 medições. A espera posterior média
pela convergência foi de 26,72 s para escrita eventual e 23,22 s para escrita
RYW; não entra no throughput. Os erros estão incluídos no total de operações
do YCSB. DP é o desvio-padrão amostral das dez rodadas.

A execução foi retomada após interrupções, preservando a mesma base e os mesmos
parâmetros. Casos parcialmente executados foram arquivados e repetidos e não
entram na tabela. Trata-se de medição local, e a variação do computador ainda
pode influenciar os resultados.

## Preparar e executar no PowerShell

Para ampliar a execucao salva para 10 rodadas no total, preservando a primeira:

```powershell
python benchmarks/run_benchmarks.py --resume benchmarks/results/20260928-173611 --total-repetitions 10
```

Isso completa 10 medicoes de cada um dos 9 cenarios (90 execucoes), mantendo
os parametros e a base originais. Para calcular as medias depois que terminar:

```powershell
python benchmarks/summarize_benchmarks.py benchmarks/results/20260928-173611
```

O calculo confere todos os arquivos brutos antes de gerar `medias.html`,
`medias.md` e `medias.json`. As medias sao aritmeticas por cenario, com o mesmo
peso por rodada; o desvio-padrao e amostral. Erros sao somados. A media dos
p95 individuais nao representa um p95 combinado das operacoes.

Compile o YCSB uma vez, na raiz do projeto:

```powershell
cd C:\codigos\replicas\YCSB-master
mvn -Psource-run -pl coordenador -am package -DskipTests
cd ..
```

Execute a comparacao inicial, com 1.000 operacoes por caso:

```powershell
python benchmarks/run_benchmarks.py --operations 1000
```

Se Java nao estiver no PATH, informe o executavel:

```powershell
python benchmarks/run_benchmarks.py --operations 1000 --java 'C:\Program Files\Java\jdk-21\bin\java.exe'
```

Para uma comparacao mais longa, com tres rodadas de 10.000 operacoes por caso:

```powershell
python benchmarks/run_benchmarks.py --operations 10000 --repetitions 3
```

Para retomar uma execucao interrompida depois da carga inicial:

```powershell
python benchmarks/run_benchmarks.py --resume benchmarks/results/20260928-173611
```

Use a pasta da sua execucao. Os parametros originais sao recuperados e os
casos concluidos sao preservados. O caso interrompido e arquivado e repetido
desde a base inicial. A retomada valida a base, os fontes e as versoes do
ambiente antes de continuar. Encerre a execucao anterior antes de retomar.

O padrao e 1.000 registros, 10.000 operacoes, 8 threads e atraso de propagacao
de 1 segundo. Ajuste com `--records`, `--operations`, `--threads`, `--delay` e
`--repetitions`. Encerre outros benchmarks antes de iniciar uma comparacao.

## Metodologia

- Carrega uma base com YCSB em `strong`, usando uma thread e ate cinco novas
  tentativas por registro em caso de falha. A carga nao entra nos resultados
  medidos e deve terminar com todos os registros confirmados. Falhas e novas
  tentativas da carga ficam registradas separadamente.
- Cada caso parte de uma copia identica dessa base e inicia novos servidores.
- Executa um caso por vez e registra o comando exato utilizado em `command.json`.
- Aguarda a igualdade de todos os valores e versoes das tres replicas antes
  de encerrar os processos. A espera adicional aparece separada na tabela.
- Encerra somente os processos que o script iniciou, inclusive em caso de erro.
- Alterna a ordem dos modos entre rodadas. Nao faz aquecimento dedicado;
  cada medicao inicia uma nova JVM. As chaves e operacoes sao sorteadas pelo YCSB.

Os arquivos ficam em `benchmarks/results/AAAAMMDD-HHMMSS/`:

- `comparacao.html`: tabela para abrir no navegador.
- `comparacao.md`: mesma tabela em Markdown.
- `results.json`: resultados numericos, parametros, ambiente e hashes dos fontes.
- Pastas de cada caso: `metrics.txt` com a saida bruta do YCSB,
  `command.json` e `ycsb.log`.
- Os logs dos servidores e as bases de dados ficam no disco para diagnostico,
  mas sao ignorados pelo Git.

Ops/s maior e latencia menor representam melhor desempenho. Compare tambem
os erros: o throughput do YCSB inclui operacoes que falharam. As latencias da
tabela sao das operacoes bem-sucedidas; latencias de falhas, quando presentes,
ficam nas metricas brutas em grupos como `READ-FAILED`.

O teste e local, com cliente e servidores no mesmo computador. O atraso
configurado e um atraso do replicador, nao uma simulacao completa de rede.
Uma unica rodada e exploratoria; variacoes pequenas nao estabelecem um vencedor.
O benchmark de desempenho nao comprova as garantias de consistencia.

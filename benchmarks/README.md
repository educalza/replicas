# Benchmarks comparativos

O script `run_benchmarks.py` executa o YCSB nos modos `strong`, `eventual` e
`ryw`, para leitura, escrita (UPDATE) e carga mista (50% de cada).
Ele cria processos, portas locais e arquivos de dados exclusivos para cada
caso, sem alterar os arquivos da pasta `data` nem utilizar servidores ja abertos.

## Comparacao executada

Resultado de 28/09/2026, com 1.000 registros, 1.000 operacoes por caso,
8 threads e uma rodada:

| Modo | Leitura (ops/s) | Escrita (ops/s) | Misto (ops/s) | Erros nas 3.000 operacoes |
| --- | ---: | ---: | ---: | ---: |
| strong | 28,16 | 4,64 | 9,45 | 14 |
| eventual | 214,27 | 20,95 | 38,98 | 2 |
| ryw | 218,87 | 24,36 | 39,56 | 4 |

[Tabela completa em HTML](results/20260928-173611/comparacao.html),
[tabela em Markdown](results/20260928-173611/comparacao.md) e
[metricas e parametros em JSON](results/20260928-173611/results.json).

Todas as replicas convergiram ao final dos nove casos. Na carga de escrita,
eventual e ryw precisaram de mais 28,61 s e 22,06 s, respectivamente, depois
que o YCSB terminou. Essa espera nao faz parte do throughput acima.
Os erros estao incluidos no total de operacoes do YCSB.

A execucao foi interrompida e retomada apos quatro casos completos, preservando
a mesma base e os mesmos parametros. O caso parcialmente executado foi
arquivado e repetido; nao entrou na tabela. Trata-se de uma medicao exploratoria
local, sem repeticoes para estimar variabilidade.

## Preparar e executar no PowerShell

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

# Armazenamento replicado HTTP/REST

As tres replicas possuem arquivos JSON independentes. O coordenador e o unico
ponto acessado pelos clientes e aplica o modo de consistencia escolhido.

Nao ha dependencias externas: basta Python 3.10 ou superior.

## Executar

Abra tres terminais na pasta do projeto:

```bash
python3 replica.py --id 1 --port 5001
python3 replica.py --id 2 --port 5002
python3 replica.py --id 3 --port 5003
```

Em um quarto terminal, escolha um modo para o coordenador:

```bash
python3 coordenador.py --mode strong
python3 coordenador.py --mode eventual
python3 coordenador.py --mode ryw
```

- `strong`: serializa leituras e escritas. A escrita so confirma sucesso depois
  que todas as replicas gravarem; a leitura valida todas sob o mesmo bloqueio,
  sem observar uma escrita pela metade. Se uma escrita falhar parcialmente,
  retorna `503`, tenta concluir a sincronizacao em segundo plano e impede
  leituras dessa chave ate a recuperacao.
- `eventual`: confirma a escrita em uma replica e propaga para as outras em
  segundo plano. Leituras alternam entre replicas e podem retornar um valor
  antigo (ou `404` para uma chave ainda nao propagada). Falhas de propagacao
  sao repetidas ate a replica voltar ou uma escrita mais nova substituir a antiga.
- `ryw`: usa a mesma propagacao assincrona, mas fixa cada `X-Client-ID` em uma
  replica. Depois de uma escrita confirmada, o cliente le sua propria escrita
  ou uma escrita posterior da mesma chave. Se sua replica estiver indisponivel,
  retorna erro, sem redirecionar a leitura para uma copia possivelmente atrasada.

Os modos assincronos aguardam apenas uma confirmacao na requisicao de escrita;
o modo forte aguarda todas. O desempenho real depende da carga e das replicas.
`--replication-delay 1` (padrao) define o atraso inicial de propagacao em segundos;
use `--replication-delay 0` para propagar assim que possivel. O atraso e contado
desde o agendamento de cada escrita, sem acrescentar uma pausa inteira por item.

Cada escrita recebe uma versao ordenada, persistida junto ao valor nas replicas.
Tentativas repetidas da mesma escrita sao idempotentes; versoes antigas nao
sobrescrevem novas, inclusive quando uma requisicao termina depois de um timeout.
Arquivos JSON existentes sem versao continuam sendo aceitos.

Execute um unico coordenador para o conjunto de replicas e acesse os dados
pela porta dele. A garantia forte se aplica as operacoes por esse coordenador:
os arquivos sao atualizados em momentos distintos, mas leituras de clientes
nao observam estados intermediarios. Ao iniciar o modo forte, use replicas
com os mesmos dados; divergencias preexistentes retornam `409` e podem ser
resolvidas gravando novamente a chave pelo coordenador.

A fila de propagacao fica em memoria: mantenha o coordenador ativo e aguarde
a convergencia antes de encerra-lo ou trocar de modo. Pendencias nao sobrevivem
a reinicios. Mantenha tambem a mesma lista e ordem de replicas no modo `ryw`,
pois ela determina a replica de cada cliente. As versoes usam o relogio do
coordenador; se ele retroceder entre reinicios, uma escrita pode ser recusada
ate uma nova tentativa receber uma versao superior a persistida.

Os dados ficam em `data/replica1.json`, `data/replica2.json` e
`data/replica3.json`.

## API

Gravar um valor:

```bash
curl -X POST http://localhost:5000/write \
  -H 'Content-Type: application/json' \
  -d '{"chave":"produto1","valor":75}'
```

Ler um valor (as duas formas sao aceitas):

```bash
curl http://localhost:5000/read/produto1
curl 'http://localhost:5000/read?chave=produto1'
```

Verificar a replica:

```bash
curl http://localhost:5000/health
```

No modo `ryw`, envie o mesmo identificador nas operacoes do mesmo cliente.
O cabecalho `X-Client-ID` e obrigatorio e nao pode ser vazio; sua ausencia retorna
`400`. Clientes diferentes devem usar identificadores diferentes:

```bash
curl -X POST http://localhost:5000/write \
  -H 'Content-Type: application/json' -H 'X-Client-ID: cliente-a' \
  -d '{"chave":"produto1","valor":80}'
curl -H 'X-Client-ID: cliente-a' http://localhost:5000/read/produto1
```

Respostas usam `200` em caso de sucesso, `400` para requisicao invalida e
`404` quando a rota ou a chave nao existe, `409` para divergencia detectada e
`503` quando a operacao nao pode ser confirmada. Um erro de escrita `503` nao
significa cancelamento: a escrita pode ser concluida pelas novas tentativas.

## Benchmark com YCSB

Para executar automaticamente os tres modos com leitura, escrita e carga mista,
gerando uma tabela de comparacao, consulte [benchmarks/README.md](benchmarks/README.md).
O executor usa dados e processos separados dos servidores iniciados manualmente.
Veja a [comparacao executada dos tres modos](benchmarks/README.md#comparacao-executada).

O binding `coordenador` usa `POST /write` para `insert` e `update`, e
`GET /read` para `read`. Cada thread envia um `X-Client-ID` estavel, necessario
para o modo `ryw`. As chaves sao prefixadas com o nome da tabela YCSB.

Requer Java e Maven. Com as tres replicas e o coordenador em execucao, rode:

```bash
cd YCSB-master
mvn -pl coordenador -am package -DskipTests
./bin/ycsb load coordenador -P coordenador/workload -threads 8 \
  -p coordenador.url=http://127.0.0.1:5000
./bin/ycsb run coordenador -P coordenador/workload -threads 8 \
  -p coordenador.url=http://127.0.0.1:5000
```

Para medir somente leituras, acrescente `-p readproportion=1 -p updateproportion=0`
ao comando `run`. Para somente escritas, use
`-p readproportion=0 -p updateproportion=1`. O `load` deve ser executado antes
do teste de leitura. Ajuste `recordcount`, `operationcount` e `-threads` para
o experimento. O resultado `[OVERALL], Throughput(ops/sec)` mostra as operacoes
por segundo; confira tambem as contagens `OK` e de erros por operacao.

O binding oferece `-p coordenador.timeout.ms=5000` para ajustar o tempo limite
HTTP em milissegundos. `scan` e `delete` nao sao implementados porque a API do
coordenador nao oferece essas operacoes. O workload fornecido usa um campo por
registro, pois cada `write` substitui o valor inteiro da chave.

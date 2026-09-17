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

- `strong`: a escrita aguarda as tres replicas e a leitura valida as tres.
- `eventual`: confirma uma replica e propaga para as outras em segundo plano.
- `ryw`: fixa o cliente em uma replica, garantindo a leitura das proprias
  escritas, e propaga para as demais em segundo plano.

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

No modo `ryw`, envie o mesmo identificador nas operacoes do mesmo cliente:

```bash
curl -X POST http://localhost:5000/write \
  -H 'Content-Type: application/json' -H 'X-Client-ID: cliente-a' \
  -d '{"chave":"produto1","valor":80}'
curl -H 'X-Client-ID: cliente-a' http://localhost:5000/read/produto1
```

Respostas usam `200` em caso de sucesso, `400` para requisicao invalida e
`404` quando a rota ou a chave nao existe.

## Benchmark com YCSB

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

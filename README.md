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

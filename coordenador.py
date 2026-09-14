#!/usr/bin/env python3
"""Gateway HTTP com consistencia strong, eventual ou read-your-writes (RYW)."""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlparse
from urllib.request import Request, urlopen


DEFAULT_REPLICAS = (
    "http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"
)


class ReplicaUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ReplicaResponse:
    status: int
    body: dict


class ReplicaClient:
    def __init__(self, urls: tuple[str, ...], timeout: float):
        self.urls = tuple(url.rstrip("/") for url in urls)
        self.timeout = timeout

    def _request(self, index: int, path: str, payload: dict | None = None) -> ReplicaResponse:
        data, headers = None, {}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.urls[index] + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return ReplicaResponse(response.status, json.loads(response.read()))
        except HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {"erro": "resposta invalida da replica"}
            return ReplicaResponse(exc.code, body)
        except (URLError, TimeoutError, OSError) as exc:
            raise ReplicaUnavailable(
                f"replica {self.urls[index]} indisponivel: {exc}"
            ) from exc

    def read(self, index: int, key: str) -> ReplicaResponse:
        return self._request(index, "/read/" + quote(key, safe=""))

    def write(self, index: int, key: str, value) -> ReplicaResponse:
        return self._request(index, "/write", {"chave": key, "valor": value})


class Coordinator:
    def __init__(self, mode: str, replicas: tuple[str, ...], timeout: float, delay: float):
        self.mode = mode
        self.client = ReplicaClient(replicas, timeout)
        self.delay = delay
        self._round_robin = 0
        self._state_lock = threading.Lock()
        # Mantem a ordem das escritas durante a propagacao assincrona.
        self._write_lock = threading.Lock()
        self._versions: dict[str, int] = {}
        self._replication_queue: queue.Queue[tuple[str, object, int, int] | None] = queue.Queue()
        self._worker = threading.Thread(target=self._replicate_worker, daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._replication_queue.put(None)

    def _replicate_worker(self) -> None:
        while True:
            task = self._replication_queue.get()
            if task is None:
                self._replication_queue.task_done()
                return
            key, value, source, version = task
            if self.delay:
                time.sleep(self.delay)
            with self._write_lock:
                # Uma propagacao atrasada nunca pode sobrescrever uma escrita mais nova.
                if self._versions.get(key) != version:
                    self._replication_queue.task_done()
                    continue
                for index in range(len(self.client.urls)):
                    if index == source:
                        continue
                    try:
                        self.client.write(index, key, value)
                    except ReplicaUnavailable as exc:
                        print(f"[replicacao assincrona] {exc}")
            self._replication_queue.task_done()

    def _next_replica(self) -> int:
        with self._state_lock:
            index = self._round_robin % len(self.client.urls)
            self._round_robin += 1
            return index

    def _client_replica(self, client_id: str) -> int:
        digest = hashlib.sha256(client_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % len(self.client.urls)

    def write(self, key: str, value, client_id: str) -> tuple[int, dict]:
        if self.mode == "strong":
            succeeded, errors = [], []
            with self._write_lock:
                for index, url in enumerate(self.client.urls):
                    try:
                        response = self.client.write(index, key, value)
                        if response.status == 200:
                            succeeded.append(url)
                        else:
                            errors.append({"replica": url, "status": response.status})
                    except ReplicaUnavailable as exc:
                        errors.append({"replica": url, "erro": str(exc)})
            if errors:
                return 503, {
                    "erro": "nao foi possivel confirmar a escrita em todas as replicas",
                    "replicas_atualizadas": succeeded, "falhas": errors, "modo": self.mode,
                }
            return 200, {
                "mensagem": "valor gravado", "chave": key, "valor": value,
                "replicas_confirmadas": len(succeeded), "modo": self.mode,
            }

        source = (self._client_replica(client_id) if self.mode == "ryw"
                  else self._next_replica())
        with self._write_lock:
            try:
                response = self.client.write(source, key, value)
            except ReplicaUnavailable as exc:
                return 503, {"erro": str(exc), "modo": self.mode}
            if response.status != 200:
                return 502, {"erro": "a replica recusou a escrita", "detalhes": response.body}
            version = self._versions.get(key, 0) + 1
            self._versions[key] = version
            self._replication_queue.put((key, value, source, version))
        return 200, {
            "mensagem": "valor gravado", "chave": key, "valor": value,
            "replica_confirmada": self.client.urls[source],
            "propagacao": "assincrona", "modo": self.mode,
        }

    def read(self, key: str, client_id: str) -> tuple[int, dict]:
        if self.mode == "strong":
            responses = []
            for index, url in enumerate(self.client.urls):
                try:
                    responses.append((url, self.client.read(index, key)))
                except ReplicaUnavailable as exc:
                    return 503, {"erro": str(exc), "modo": self.mode}
            if all(response.status == 404 for _, response in responses):
                return 404, {"erro": "chave nao encontrada", "chave": key, "modo": self.mode}
            if any(response.status != 200 for _, response in responses):
                return 409, {"erro": "replicas divergentes", "chave": key, "modo": self.mode}
            values = [response.body.get("valor") for _, response in responses]
            if any(value != values[0] for value in values[1:]):
                return 409, {
                    "erro": "replicas divergentes", "chave": key,
                    "valores": values, "modo": self.mode,
                }
            return 200, {
                "chave": key, "valor": values[0], "modo": self.mode,
                "replicas_consultadas": len(responses),
            }

        index = (self._client_replica(client_id) if self.mode == "ryw"
                 else self._next_replica())
        try:
            response = self.client.read(index, key)
        except ReplicaUnavailable as exc:
            return 503, {"erro": str(exc), "modo": self.mode}
        body = dict(response.body)
        body["modo"] = self.mode
        body["replica_consultada"] = self.client.urls[index]
        return response.status, body


def make_handler(coordinator: Coordinator):
    class CoordinatorHandler(BaseHTTPRequestHandler):
        server_version = "CoordenadorHTTP/1.0"

        def _json(self, status: int, body: dict) -> None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _client_id(self) -> str:
            return self.headers.get("X-Client-ID", self.client_address[0]).strip()

        def _read_key(self) -> str | None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/read/"):
                return unquote(parsed.path[len("/read/"):]).strip()
            if parsed.path == "/read":
                return parse_qs(parsed.query).get("chave", [""])[0].strip()
            return None

        def do_GET(self) -> None:  # noqa: N802
            if urlparse(self.path).path == "/health":
                self._json(200, {"status": "ok", "servico": "coordenador",
                                 "modo": coordinator.mode})
                return
            key = self._read_key()
            if key is None:
                self._json(404, {"erro": "rota nao encontrada"})
            elif not key:
                self._json(400, {"erro": "informe a chave"})
            else:
                status, body = coordinator.read(key, self._client_id())
                self._json(status, body)

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/write":
                self._json(404, {"erro": "rota nao encontrada"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"erro": "corpo JSON invalido"})
                return
            if not isinstance(payload, dict):
                self._json(400, {"erro": "o corpo deve ser um objeto JSON"})
                return
            key = payload.get("chave")
            if not isinstance(key, str) or not key.strip():
                self._json(400, {"erro": "'chave' deve ser uma string nao vazia"})
                return
            if "valor" not in payload:
                self._json(400, {"erro": "campo 'valor' obrigatorio"})
                return
            status, body = coordinator.write(key.strip(), payload["valor"], self._client_id())
            self._json(status, body)

        def log_message(self, format: str, *args) -> None:
            print(f"[coordenador/{coordinator.mode}] {self.address_string()} - {format % args}")

    return CoordinatorHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inicia o coordenador chave/valor")
    parser.add_argument("--mode", required=True, choices=("strong", "eventual", "ryw"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--replicas", nargs="+", default=list(DEFAULT_REPLICAS))
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--replication-delay", type=float, default=1.0,
                        help="atraso da propagacao assincrona, em segundos")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    coordinator = Coordinator(args.mode, tuple(args.replicas), args.timeout,
                              max(0, args.replication_delay))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(coordinator))
    print(f"Coordenador em http://{args.host}:{args.port} (modo: {args.mode})")
    print("Replicas: " + ", ".join(args.replicas))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando coordenador...")
    finally:
        server.server_close()
        coordinator.close()


if __name__ == "__main__":
    main()

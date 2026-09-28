#!/usr/bin/env python3
"""Gateway HTTP com consistencia strong, eventual ou read-your-writes (RYW)."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from http.client import HTTPException
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
                body = json.loads(response.read())
                if not isinstance(body, dict):
                    raise ValueError("a resposta da replica deve ser um objeto JSON")
                return ReplicaResponse(response.status, body)
        except HTTPError as exc:
            try:
                body = json.loads(exc.read())
                if not isinstance(body, dict):
                    raise ValueError("resposta invalida da replica")
            except (ValueError, OSError, HTTPException):
                body = {"erro": "resposta invalida da replica"}
            return ReplicaResponse(exc.code, body)
        except (URLError, TimeoutError, OSError, ValueError, HTTPException) as exc:
            raise ReplicaUnavailable(
                f"replica {self.urls[index]} indisponivel: {exc}"
            ) from exc

    def read(self, index: int, key: str) -> ReplicaResponse:
        return self._request(index, "/read/" + quote(key, safe=""))

    def write(self, index: int, key: str, value, version: int) -> ReplicaResponse:
        return self._request(index, "/write", {
            "chave": key, "valor": value, "versao": version,
        })


@dataclass(frozen=True)
class ReplicationTask:
    key: str
    value: object
    version: int
    targets: tuple[int, ...]


class Coordinator:
    def __init__(self, mode: str, replicas: tuple[str, ...], timeout: float, delay: float):
        if mode not in ("strong", "eventual", "ryw"):
            raise ValueError("modo de consistencia invalido")
        if not replicas or len(set(url.rstrip("/") for url in replicas)) != len(replicas):
            raise ValueError("informe replicas distintas e nao vazias")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout deve ser positivo e finito")
        if not math.isfinite(delay) or delay < 0:
            raise ValueError("replication-delay deve ser nao negativo e finito")
        self.mode = mode
        self.client = ReplicaClient(replicas, timeout)
        self.delay = delay
        self._round_robin = 0
        self._state_lock = threading.Lock()
        # No modo forte, leituras e escritas compartilham a mesma exclusao.
        self._write_lock = threading.Lock()
        self._replica_locks = [threading.Lock() for _ in replicas]
        self._versions: dict[str, int] = {}
        self._last_version = 0
        self._pending_strong: set[str] = set()
        self._condition = threading.Condition(self._state_lock)
        self._replication_queue: list[tuple[float, int, ReplicationTask]] = []
        self._closed = False
        self._worker = threading.Thread(target=self._replicate_worker, daemon=True)
        self._worker.start()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._worker.join(timeout=self.client.timeout + 1)

    def _schedule(self, task: ReplicationTask, delay: float) -> None:
        with self._condition:
            if not self._closed:
                heapq.heappush(self._replication_queue,
                               (time.monotonic() + delay, task.version, task))
                self._condition.notify()

    def _new_version(self, key: str) -> int:
        with self._state_lock:
            self._last_version = max(time.time_ns(), self._last_version + 1)
            self._versions[key] = self._last_version
            return self._last_version

    def _is_current(self, task: ReplicationTask) -> bool:
        with self._state_lock:
            return not self._closed and self._versions.get(task.key) == task.version

    def _send_write(self, index: int, key: str, value, version: int) -> ReplicaResponse:
        try:
            response = self.client.write(index, key, value, version)
        except ReplicaUnavailable as exc:
            return ReplicaResponse(503, {"erro": str(exc)})
        # Se o relogio retroceder entre execucoes, a proxima escrita usa uma
        # versao maior que a persistida. Nunca substituimos silenciosamente
        # um valor mais novo por uma tentativa antiga.
        observed = response.body.get("versao", 0)
        if isinstance(observed, int):
            with self._state_lock:
                self._last_version = max(self._last_version, observed)
        return response

    def _replicate_worker(self) -> None:
        while True:
            with self._condition:
                while True:
                    if self._closed:
                        return
                    if not self._replication_queue:
                        self._condition.wait()
                        continue
                    ready_at, _, task = self._replication_queue[0]
                    remaining = ready_at - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(remaining)
                        continue
                    heapq.heappop(self._replication_queue)
                    break
            # Propagacao eventual nao segura o lock global das escritas.
            guard = self._write_lock if self.mode == "strong" else nullcontext()
            with guard:
                failed = []
                for index in task.targets:
                    with self._replica_locks[index]:
                        if not self._is_current(task):
                            break
                        response = self._send_write(index, task.key, task.value, task.version)
                        if response.status != 200:
                            failed.append(index)
                if not self._is_current(task):
                    continue
                if failed:
                    self._schedule(ReplicationTask(task.key, task.value, task.version,
                                                   tuple(failed)), max(0.1, self.delay))
                elif self.mode == "strong":
                    self._pending_strong.discard(task.key)

    def _next_replica(self) -> int:
        with self._state_lock:
            index = self._round_robin % len(self.client.urls)
            self._round_robin += 1
            return index

    def _client_replica(self, client_id: str) -> int:
        digest = hashlib.sha256(client_id.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % len(self.client.urls)

    def write(self, key: str, value, client_id: str) -> tuple[int, dict]:
        if self.mode == "ryw" and not client_id:
            return 400, {"erro": "X-Client-ID obrigatorio no modo ryw"}
        if self.mode == "strong":
            succeeded, errors = [], []
            with self._write_lock:
                version = self._new_version(key)
                for index, url in enumerate(self.client.urls):
                    with self._replica_locks[index]:
                        response = self._send_write(index, key, value, version)
                        if response.status == 200:
                            succeeded.append(url)
                        else:
                            errors.append({"replica": url, "status": response.status,
                                           "detalhes": response.body})
                if errors:
                    self._pending_strong.add(key)
                    self._schedule(ReplicationTask(key, value, version,
                                                   tuple(range(len(self.client.urls)))), 0.1)
                else:
                    self._pending_strong.discard(key)
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
            version = self._new_version(key)
            with self._replica_locks[source]:
                response = self._send_write(source, key, value, version)
            # Mesmo um timeout pode ter gravado na origem. Repetir a mesma
            # versao e idempotente e faz todas convergirem nesse caso tambem.
            targets = tuple(index for index in range(len(self.client.urls))
                            if index != source or response.status != 200)
            self._schedule(ReplicationTask(key, value, version, targets), self.delay)
            if response.status != 200:
                return 503, {"erro": "nao foi possivel confirmar a escrita",
                             "detalhes": response.body, "modo": self.mode}
        return 200, {
            "mensagem": "valor gravado", "chave": key, "valor": value,
            "replica_confirmada": self.client.urls[source],
            "propagacao": "assincrona", "modo": self.mode,
        }

    def read(self, key: str, client_id: str) -> tuple[int, dict]:
        if self.mode == "ryw" and not client_id:
            return 400, {"erro": "X-Client-ID obrigatorio no modo ryw"}
        if self.mode == "strong":
            with self._write_lock:
                return self._read_strong(key)

        index = (self._client_replica(client_id) if self.mode == "ryw"
                 else self._next_replica())
        try:
            with self._replica_locks[index]:
                response = self.client.read(index, key)
        except ReplicaUnavailable as exc:
            return 503, {"erro": str(exc), "modo": self.mode}
        body = dict(response.body)
        body["modo"] = self.mode
        body["replica_consultada"] = self.client.urls[index]
        return response.status, body

    def _read_strong(self, key: str) -> tuple[int, dict]:
        if key in self._pending_strong:
            return 503, {"erro": "escrita aguardando sincronizacao das replicas",
                         "chave": key, "modo": self.mode}
        responses = []
        for index, url in enumerate(self.client.urls):
            try:
                response = self.client.read(index, key)
            except ReplicaUnavailable as exc:
                return 503, {"erro": str(exc), "modo": self.mode}
            if response.status not in (200, 404):
                return 503, {"erro": "nao foi possivel consultar todas as replicas",
                             "replica": url, "detalhes": response.body, "modo": self.mode}
            responses.append(response)
        if all(response.status == 404 for response in responses):
            return 404, {"erro": "chave nao encontrada", "chave": key, "modo": self.mode}
        if any(response.status != 200 for response in responses):
            return 409, {"erro": "replicas divergentes", "chave": key, "modo": self.mode}
        values = [response.body.get("valor") for response in responses]
        if any(value != values[0] for value in values[1:]):
            return 409, {
                "erro": "replicas divergentes", "chave": key,
                "valores": values, "modo": self.mode,
            }
        return 200, {
            "chave": key, "valor": values[0], "modo": self.mode,
            "replicas_consultadas": len(responses),
        }


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
            return self.headers.get("X-Client-ID", "").strip()

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
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout deve ser positivo e finito")
    if not math.isfinite(args.replication_delay) or args.replication_delay < 0:
        parser.error("--replication-delay deve ser nao negativo e finito")
    if len(set(url.rstrip("/") for url in args.replicas)) != len(args.replicas):
        parser.error("--replicas deve conter enderecos distintos")
    return args


def main() -> None:
    args = parse_args()
    coordinator = Coordinator(args.mode, tuple(args.replicas), args.timeout,
                              args.replication_delay)
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

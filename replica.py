#!/usr/bin/env python3
"""Servidor HTTP de uma replica do armazenamento chave/valor."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


class VersionConflict(Exception):
    def __init__(self, version: int):
        self.version = version
        super().__init__("a replica ja possui uma escrita mais recente ou conflitante")


class DataStore:
    """Armazenamento JSON persistente e seguro para acesso por varias threads."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"produto1": {"valor": 50}})

    def _load(self) -> dict:
        try:
            with self.path.open(encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"nao foi possivel ler {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"{self.path} deve conter um objeto JSON")
        return data

    def _save(self, data: dict) -> None:
        # Substituicao atomica evita deixar JSON parcial se o processo for interrompido.
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=4)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def read(self, key: str):
        with self._lock:
            data = self._load()
            return data.get(key)

    def write(self, key: str, value, version: int | None = None) -> int:
        with self._lock:
            data = self._load()
            current = data.get(key, {})
            current_version = current.get("versao", 0)
            if version is None:
                version = max(time.time_ns(), current_version + 1)
            if version < current_version:
                raise VersionConflict(current_version)
            if version == current_version:
                if current.get("valor") != value:
                    raise VersionConflict(current_version)
                return version
            data[key] = {"valor": value, "versao": version}
            self._save(data)
            return version


def make_handler(store: DataStore, replica_id: str):
    class ReplicaHandler(BaseHTTPRequestHandler):
        server_version = "ReplicaHTTP/1.0"

        def _json(self, status: int, body: dict) -> None:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _key_from_read_url(self) -> str | None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/read/"):
                return unquote(parsed.path[len("/read/") :]).strip()
            if parsed.path == "/read":
                return parse_qs(parsed.query).get("chave", [""])[0].strip()
            return None

        def do_GET(self) -> None:  # noqa: N802 (nome definido por BaseHTTPRequestHandler)
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._json(200, {"status": "ok", "replica": replica_id})
                return

            key = self._key_from_read_url()
            if key is None:
                self._json(404, {"erro": "rota nao encontrada"})
            elif not key:
                self._json(400, {"erro": "informe a chave"})
            else:
                try:
                    item = store.read(key)
                except RuntimeError as exc:
                    self._json(500, {"erro": str(exc)})
                    return
                if item is None:
                    self._json(404, {"erro": "chave nao encontrada", "chave": key})
                else:
                    self._json(200, {"chave": key, **item, "replica": replica_id})

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
            version = payload.get("versao")
            if "versao" in payload and (type(version) is not int or version <= 0):
                self._json(400, {"erro": "'versao' deve ser um inteiro positivo"})
                return

            key = key.strip()
            try:
                version = store.write(key, payload["valor"], version)
            except VersionConflict as exc:
                self._json(409, {"erro": str(exc), "versao": exc.version})
                return
            except (RuntimeError, OSError) as exc:
                self._json(500, {"erro": str(exc)})
                return
            self._json(
                200,
                {"mensagem": "valor gravado", "chave": key,
                 "valor": payload["valor"], "replica": replica_id, "versao": version},
            )

        def log_message(self, format: str, *args) -> None:
            print(f"[replica {replica_id}] {self.address_string()} - {format % args}")

    return ReplicaHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inicia uma replica chave/valor HTTP")
    parser.add_argument("--id", required=True, help="identificador da replica")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--data-file", type=Path, help="arquivo JSON da replica")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_file = args.data_file or Path("data") / f"replica{args.id}.json"
    store = DataStore(data_file)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, args.id))
    print(f"Replica {args.id} em http://{args.host}:{args.port} (dados: {data_file})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando replica...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

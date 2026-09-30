#!/usr/bin/env python3
"""Executa YCSB em replicas isoladas e gera uma comparacao reproduzivel."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
YCSB = ROOT / "YCSB-master"
PROFILES = {"leitura": (1, 0), "escrita": (0, 1), "misto": (0.5, 0.5)}
MODES = ("strong", "eventual", "ryw")
CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def spawn(command, log):
    return subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=CREATE_FLAGS)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class Cluster:
    def __init__(self, directory, mode, delay, baseline=None):
        self.directory = directory
        self.processes = []
        self.logs = []
        self.files = []
        self.mode = mode
        self.delay = delay
        self.baseline = baseline

    def __enter__(self):
        self.directory.mkdir(parents=True)
        reservations = []
        try:
            for _ in range(4):
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                reservations.append(listener)
            ports = [sock.getsockname()[1] for sock in reservations]
        finally:
            for sock in reservations:
                sock.close()
        self.url = f"http://127.0.0.1:{ports[0]}"
        replicas = [f"http://127.0.0.1:{port}" for port in ports[1:]]
        try:
            for index, port in enumerate(ports[1:], 1):
                path = self.directory / f"replica{index}.json"
                self.files.append(path)
                if self.baseline:
                    shutil.copyfile(self.baseline, path)
                else:
                    path.write_text("{}", encoding="utf-8")
                self._start([sys.executable, "-u", str(ROOT / "replica.py"), "--id", str(index),
                             "--port", str(port), "--data-file", str(path)], f"replica{index}")
            for url in replicas:
                self._health(url)
            self._start([sys.executable, "-u", str(ROOT / "coordenador.py"), "--mode", self.mode,
                         "--port", str(ports[0]), "--replication-delay", str(self.delay),
                         "--replicas", *replicas], "coordenador")
            self._health(self.url)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _start(self, command, name):
        log = (self.directory / f"{name}.log").open("wb")
        self.logs.append(log)
        self.processes.append(spawn(command, log))

    def _health(self, url):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if any(process.poll() is not None for process in self.processes):
                raise RuntimeError(f"Servidor encerrou; confira {self.directory}")
            try:
                with urlopen(url + "/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"Servidor nao iniciou: {url}")

    def converge(self, timeout=300):
        start = time.monotonic()
        read_retries = 0
        while time.monotonic() - start < timeout:
            try:
                copies = [json.loads(path.read_text(encoding="utf-8")) for path in self.files]
            except PermissionError:
                # O Windows pode bloquear brevemente um arquivo durante replace.
                # Esta verificacao ocorre depois do YCSB; nao altera as metricas.
                read_retries += 1
                time.sleep(0.25)
                continue
            if all(copy == copies[0] for copy in copies[1:]):
                return {"converged": True, "wait_seconds": time.monotonic() - start,
                        "records": len(copies[0]), "read_retries": read_retries}
            time.sleep(0.25)
        return {"converged": False, "wait_seconds": time.monotonic() - start,
                "read_retries": read_retries}

    def __exit__(self, *args):
        for process in reversed(self.processes):
            stop(process)
        for log in self.logs:
            log.close()


def parse_metrics(path):
    metrics = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\[([^]]+)\], ([^,]+), (.+)", line)
        if match:
            group, name, value = match.groups()
            metrics.setdefault(group, {})[name] = float(value)
    if "Throughput(ops/sec)" not in metrics.get("OVERALL", {}):
        raise RuntimeError(f"Resultado incompleto: {path}")
    return metrics


def run_ycsb(args, cluster, directory, profile, load=False):
    raw = directory / "metrics.txt"
    read, update = PROFILES[profile]
    command = [args.java, "-cp", args.classpath, "site.ycsb.Client",
               "-load" if load else "-t", "-s", "-db", "site.ycsb.db.CoordenadorClient",
               "-P", str(YCSB / "coordenador" / "workload"), "-threads",
               "1" if load else str(args.threads)]
    properties = {"coordenador.url": cluster.url, "recordcount": args.records,
                  "operationcount": args.operations, "readproportion": read,
                  "updateproportion": update, "measurementtype": "hdrhistogram",
                  "exportfile": raw, "status.interval": 10}
    if load:
        properties["core_workload_insertion_retry_limit"] = 5
        properties["core_workload_insertion_retry_interval"] = 1
    for key, value in properties.items():
        command.extend(["-p", f"{key}={value}"])
    (directory / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    with (directory / "ycsb.log").open("wb") as log:
        process = spawn(command, log)
        start = time.monotonic()
        try:
            while True:
                try:
                    code = process.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - start
                    print(f"  {directory.name}: {elapsed:.0f}s em execucao", flush=True)
                    if elapsed > args.timeout:
                        raise RuntimeError(f"Tempo limite excedido: {directory}")
            if code != 0:
                raise RuntimeError(f"YCSB retornou {code}: {directory / 'ycsb.log'}")
        finally:
            stop(process)
    return parse_metrics(raw)


def summarize(metrics):
    codes = {f"{group}/{name[7:]}": int(value)
             for group in ("READ", "UPDATE", "INSERT")
             for name, value in metrics.get(group, {}).items() if name.startswith("Return=")}
    ok = sum(value for name, value in codes.items() if name.endswith("/OK"))
    total = sum(codes.values())
    result = {"ops_sec": metrics["OVERALL"]["Throughput(ops/sec)"],
              "runtime_seconds": metrics["OVERALL"]["RunTime(ms)"] / 1000,
              "ok": ok, "errors": total - ok, "total": total, "status_counts": codes}
    for operation in ("READ", "UPDATE"):
        for metric, label in (("AverageLatency(us)", "mean_ms"),
                              ("95thPercentileLatency(us)", "p95_ms")):
            value = metrics.get(operation, {}).get(metric)
            result[f"{operation.lower()}_{label}"] = None if value is None else value / 1000
    return result


def report(output, metadata, results):
    temporary = output / "results.json.tmp"
    temporary.write_text(json.dumps({"metadata": metadata, "results": results},
                                   indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output / "results.json")
    headers = ["Carga", "Modo", "Rodada", "Ops/s", "Tempo (s)", "Leitura media (ms)",
               "Leitura p95 (ms)", "Escrita media (ms)", "Escrita p95 (ms)", "OK", "Erros",
               "Espera convergencia (s)"]
    rows = []
    for result in results:
        fmt = lambda value: "—" if value is None else f"{value:.2f}"
        rows.append([result["profile"], result["mode"], str(result["round"]),
                     fmt(result["ops_sec"]), fmt(result["runtime_seconds"]),
                     *[fmt(result[key]) for key in ("read_mean_ms", "read_p95_ms",
                                                   "update_mean_ms", "update_p95_ms")],
                     str(result["ok"]), str(result["errors"]),
                     fmt(result["convergence"]["wait_seconds"])
                     if result["convergence"]["converged"] else "NAO CONVERGIU"])
    methodology = (f"{metadata['records']} registros; {metadata['operations']} operacoes por execucao; "
                   f"{metadata['threads']} threads; {metadata['repetitions']} rodada(s); "
                   f"atraso assincrono de {metadata['delay']} s. "
                   "Escrita = UPDATE; misto = 50% READ / 50% UPDATE (sorteio por operacao). "
                   "Um campo de 100 caracteres, distribuicao uniforme. "
                   "Carga inicial via YCSB em strong com 1 thread e ate 5 retries por registro, "
                   "fora da medicao. Cada caso usa uma copia "
                   "identica dessa base, novos processos e portas locais livres. "
                   "Execucoes sequenciais, sem aquecimento dedicado, com logs em arquivos. "
                   "Throughput e latencia sao os do cliente YCSB; a espera posterior pela "
                   "convergencia nao entra no tempo medido. Latencias exibidas em milissegundos "
                   "(YCSB exporta microssegundos). A convergencia compara todos os valores e "
                   "versoes persistidos; nao comprova, por si so, as garantias de consistencia. "
                   "Resultados locais exploratorios, sujeitos a variacao de carga do computador; "
                   "nao ha intervalo de confianca com uma unica rodada.")
    lines = ["# Comparacao dos modos de consistencia", "", methodology, "",
             "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    lines.extend(["", f"Ambiente: {metadata['platform']}; Python {metadata['python']}; "
                  f"Java: {metadata['java_version'].splitlines()[0]}", "",
                  "Os comandos exatos, logs e metricas brutas ficam nas pastas de cada caso. "
                  "results.json contem parametros, hashes dos fontes e todos os resultados.", ""])
    (output / "comparacao.md").write_text("\n".join(lines), encoding="utf-8")
    th = "".join(f"<th>{html.escape(label)}</th>" for label in headers)
    trs = "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
                  for row in rows)
    page = ('<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Comparacao de consistencia</title><style>'
            'body{font:16px system-ui;margin:40px;background:#f4f6fa;color:#182437}'
            'h1{font-size:28px}p{line-height:1.65;max-width:1050px}'
            '.table{overflow:auto;background:white;border:1px solid #dce2ec;border-radius:12px}'
            'table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}'
            'th,td{padding:14px;text-align:right;border-bottom:1px solid #e5e9ef;white-space:nowrap}'
            'th{background:#172d4d;color:white}th:first-child,td:first-child{text-align:left}'
            'tr:nth-child(even){background:#f0f4f9}</style>'
            '<h1>Comparacao dos modos de consistencia</h1>'
            f'<p>{html.escape(methodology)}</p><div class="table"><table><thead><tr>{th}</tr>'
            f'</thead><tbody>{trs}</tbody></table></div>'
            '<p>Ops/s: maior e melhor. Latencia: menor e melhor. '
            'Consulte tambem os erros e a espera pela convergencia.</p>'
            '<p><a href="results.json">Resultados e parametros em JSON</a> · '
            '<a href="comparacao.md">Tabela em Markdown</a></p></html>')
    (output / "comparacao.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--java", default=shutil.which("java"))
    parser.add_argument("--records", type=int, default=1000)
    parser.add_argument("--operations", type=int, default=10000)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--resume", type=Path, help="retoma uma pasta de resultados existente")
    parser.add_argument("--total-repetitions", type=int,
                        help="amplia uma execucao retomada para este total de rodadas")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "benchmarks" / "results" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    args = parser.parse_args()
    if args.total_repetitions is not None and (not args.resume or args.total_repetitions < 1):
        parser.error("--total-repetitions exige --resume e um total positivo")
    if not args.java:
        parser.error("Java nao encontrado; informe --java com o caminho de java.exe")
    if min(args.records, args.operations, args.threads, args.repetitions) < 1 or args.delay < 0:
        parser.error("contagens devem ser positivas e delay nao negativo")
    jars = [*sorted((YCSB / "core" / "target").glob("*.jar")),
            *sorted((YCSB / "core" / "target" / "dependency").glob("*.jar")),
            *sorted((YCSB / "coordenador" / "target").glob("*.jar")),
            *sorted((YCSB / "coordenador" / "target" / "dependency").glob("*.jar"))]
    if not any(path.name.startswith("coordenador-binding") for path in jars):
        parser.error("Compile antes: mvn -Psource-run -pl coordenador -am package -DskipTests")
    args.classpath = os.pathsep.join(str(path) for path in jars)
    output = (args.resume or args.output).resolve()
    if not args.resume:
        output.mkdir(parents=True, exist_ok=False)
    java_version = subprocess.run([args.java, "-version"], capture_output=True, text=True,
                                  creationflags=CREATE_FLAGS, check=True)
    metadata = {key: getattr(args, key) for key in ("records", "operations", "threads",
                                                  "repetitions", "delay")}
    metadata.update({"started_utc": datetime.now(timezone.utc).isoformat(),
                     "platform": platform.platform(), "python": sys.version,
                     "java_version": java_version.stderr or java_version.stdout,
                     "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                       for name in ("coordenador.py", "replica.py")}})
    results = []
    baseline = output / "baseline.json"
    if args.resume:
        saved = json.loads((output / "results.json").read_text(encoding="utf-8"))
        previous = saved["metadata"]
        for key in ("source_sha256", "python", "java_version", "platform"):
            if metadata[key] != previous[key]:
                raise RuntimeError(f"Ambiente mudou desde a execucao original: {key}")
        if hashlib.sha256(baseline.read_bytes()).hexdigest() != previous["baseline_sha256"]:
            raise RuntimeError("A base salva foi alterada")
        metadata = previous
        results = saved["results"]
        identities = {(row["round"], row["profile"], row["mode"]) for row in results}
        if len(identities) != len(results) or any(
                row["total"] != metadata["operations"] or not row["convergence"]["converged"]
                for row in results):
            raise RuntimeError("Resultados existentes duplicados, incompletos ou sem convergencia")
        if args.total_repetitions is not None:
            if args.total_repetitions < metadata["repetitions"]:
                parser.error("O novo total nao pode reduzir as rodadas existentes")
            if args.total_repetitions > metadata["repetitions"]:
                snapshot = output / f"results-before-{args.total_repetitions}-rounds.json"
                if not snapshot.exists():
                    shutil.copyfile(output / "results.json", snapshot)
                metadata["repetitions"] = args.total_repetitions
                if "finished_utc" in metadata:
                    metadata.setdefault("previous_finished_utc", []).append(metadata.pop("finished_utc"))
        for key in ("records", "operations", "threads", "repetitions", "delay"):
            setattr(args, key, metadata[key])
        metadata.setdefault("resumed_utc", []).append(datetime.now(timezone.utc).isoformat())
    metadata["status"] = "running"
    report(output, metadata, results)
    print(f"Resultados: {output}", flush=True)
    if not args.resume:
        print("Preparando base identica com carga YCSB em strong...", flush=True)
        with Cluster(output / "load", "strong", args.delay) as cluster:
            metrics = run_ycsb(args, cluster, output / "load", "escrita", load=True)
            summary = summarize(metrics)
            if summary["ok"] != args.records:
                raise RuntimeError(f"Carga inicial incompleta: {summary}")
            convergence = cluster.converge()
            if not convergence["converged"] or convergence["records"] != args.records:
                raise RuntimeError("Base inicial nao convergiu")
            shutil.copyfile(cluster.files[0], baseline)
        metadata["baseline_sha256"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
        metadata["load"] = summary
        report(output, metadata, results)
    completed = {(row["round"], row["profile"], row["mode"]) for row in results}
    for repetition in range(1, args.repetitions + 1):
        # Alterna a ordem dos modos entre rodadas para reduzir vies de ordem.
        modes = MODES[(repetition - 1) % 3:] + MODES[:(repetition - 1) % 3]
        for profile in PROFILES:
            for mode in modes:
                if (repetition, profile, mode) in completed:
                    continue
                label = f"{repetition}-{profile}-{mode}"
                directory = output / label
                if directory.exists():
                    archive = output / (label + "-interrupted-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
                    if directory.resolve().parent != output or archive.resolve().parent != output:
                        raise RuntimeError("Pasta fora da area de resultados")
                    directory.rename(archive)
                print(f"Iniciando {label}", flush=True)
                started = datetime.now(timezone.utc).isoformat()
                with Cluster(directory, mode, args.delay, baseline) as cluster:
                    metrics = run_ycsb(args, cluster, directory, profile)
                    result = summarize(metrics)
                    result.update({"profile": profile, "mode": mode, "round": repetition,
                                   "convergence": cluster.converge(), "metrics": metrics,
                                   "started_utc": started,
                                   "finished_utc": datetime.now(timezone.utc).isoformat()})
                results.append(result)
                report(output, metadata, results)
                print(f"Concluido {label}: {result['ops_sec']:.2f} ops/s; "
                      f"{result['ok']} OK; {result['errors']} erros", flush=True)
                if result["total"] != args.operations or not result["convergence"]["converged"]:
                    raise RuntimeError(f"Execucao incompleta ou replicas divergentes: {label}")
    metadata["finished_utc"] = datetime.now(timezone.utc).isoformat()
    metadata["status"] = "complete"
    report(output, metadata, results)
    print(f"Concluido. Tabela: {output / 'comparacao.html'}", flush=True)


if __name__ == "__main__":
    main()

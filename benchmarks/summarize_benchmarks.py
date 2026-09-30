#!/usr/bin/env python3
"""Confere os resultados brutos e calcula medias por carga e modo."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import statistics

from run_benchmarks import MODES, PROFILES, parse_metrics, summarize


def aggregate(directory):
    saved = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    metadata = saved["metadata"]
    repetitions = metadata["repetitions"]
    results = saved["results"]
    expected = {(n, profile, mode) for n in range(1, repetitions + 1)
                for profile in PROFILES for mode in MODES}
    actual = {(row["round"], row["profile"], row["mode"]) for row in results}
    if actual != expected or len(results) != len(expected):
        raise ValueError(f"Esperados {len(expected)} casos distintos; encontrados {len(results)}")
    for row in results:
        case = directory / f"{row['round']}-{row['profile']}-{row['mode']}"
        original = summarize(parse_metrics(case / "metrics.txt"))
        if any(row[key] != value for key, value in original.items()):
            raise ValueError(f"Resumo diverge das metricas brutas: {case}")
        if row["total"] != metadata["operations"]:
            raise ValueError(f"Contagem de operacoes incompleta: {case}")
        if not row["convergence"]["converged"] or row["convergence"]["records"] != metadata["records"]:
            raise ValueError(f"Convergencia nao confirmada: {case}")
    summary = []
    keys = ("ops_sec", "runtime_seconds", "read_mean_ms", "read_p95_ms",
            "update_mean_ms", "update_p95_ms", "errors")
    for profile in PROFILES:
        for mode in MODES:
            runs = sorted((row for row in results if row["profile"] == profile and row["mode"] == mode),
                          key=lambda row: row["round"])
            item = {"profile": profile, "mode": mode, "n": len(runs), "statistics": {}}
            for key in (*keys, "convergence_seconds"):
                values = ([row["convergence"]["wait_seconds"] for row in runs]
                          if key == "convergence_seconds" else
                          [row[key] for row in runs if row[key] is not None])
                item["statistics"][key] = {
                    "n": len(values),
                    "mean": statistics.mean(values) if values else None,
                    "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
                    "min": min(values) if values else None,
                    "max": max(values) if values else None,
                }
            item["total_operations"] = sum(row["total"] for row in runs)
            item["total_ok"] = sum(row["ok"] for row in runs)
            item["total_errors"] = sum(row["errors"] for row in runs)
            item["error_rate_percent"] = 100 * item["total_errors"] / item["total_operations"]
            item["all_converged"] = True
            # Esta taxa considera o tempo total, diferentemente da media aritmetica.
            total_time = sum(row["runtime_seconds"] for row in runs)
            item["pooled_ops_sec"] = item["total_operations"] / total_time
            item["successful_ops_sec"] = item["total_ok"] / total_time
            summary.append(item)
    return {"generated_utc": datetime.now(timezone.utc).isoformat(), "metadata": metadata,
            "verified_runs": len(results), "summary": summary}


def format_number(value):
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def markdown_table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |",
                      "| " + " | ".join(["---"] * len(headers)) + " |",
                      *("| " + " | ".join(row) + " |" for row in rows)])


def html_table(headers, rows):
    head = "".join(f"<th>{html.escape(value)}</th>" for value in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in row) + "</tr>"
                   for row in rows)
    return f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def write_report(directory, data):
    metadata = data["metadata"]
    by_case = {(item["profile"], item["mode"]): item for item in data["summary"]}
    compact_headers = ["Modo", "Leitura: média ± DP (ops/s)", "Escrita: média ± DP (ops/s)",
                       "Misto: média ± DP (ops/s)", "Erros totais"]
    compact_rows = []
    for mode in MODES:
        cells = [mode]
        errors = 0
        for profile in PROFILES:
            item = by_case[profile, mode]
            stats = item["statistics"]["ops_sec"]
            cells.append(f"{format_number(stats['mean'])} ± {format_number(stats['sample_sd'])}")
            errors += item["total_errors"]
        cells.append(str(errors))
        compact_rows.append(cells)
    headers = ["Carga", "Modo", "N", "Média (ops/s)", "DP (ops/s)", "Tempo médio (s)",
               "Leitura média (ms)", "Média p95 leitura (ms)", "Escrita média (ms)",
               "Média p95 escrita (ms)", "Erros totais", "Erros (%)", "Convergência média (s)"]
    rows = []
    for item in data["summary"]:
        stats = item["statistics"]
        rows.append([item["profile"], item["mode"], str(item["n"]),
                     format_number(stats["ops_sec"]["mean"]),
                     format_number(stats["ops_sec"]["sample_sd"]),
                     *[format_number(stats[key]["mean"]) for key in
                       ("runtime_seconds", "read_mean_ms", "read_p95_ms", "update_mean_ms", "update_p95_ms")],
                     str(item["total_errors"]), format_number(item["error_rate_percent"]),
                     format_number(stats["convergence_seconds"]["mean"])])
    description = (f"{metadata['repetitions']} rodadas por cenário, "
                   f"{data['verified_runs']} execuções verificadas e "
                   f"{data['verified_runs'] * metadata['operations']:,} operações medidas. "
                   f"Cada execução usa {metadata['records']} registros, {metadata['operations']} operações, "
                   f"{metadata['threads']} threads e atraso assíncrono de {metadata['delay']} s. "
                   "A primeira rodada foi preservada e entrou nas médias.")
    notes = [
        "Cada média é aritmética, com o mesmo peso para cada rodada. DP é o desvio-padrão amostral (divisor N − 1).",
        "As latências são médias das métricas de operações bem-sucedidas de cada rodada. A média dos p95 não é o p95 combinado de todas as operações.",
        "O throughput do YCSB inclui tentativas que falharam. Erros são somados, sem excluir rodadas com falhas; o JSON também fornece a média de erros por rodada.",
        "A espera pela convergência é medida após o YCSB e não entra no throughput. Todas as réplicas convergiram em todas as execuções incluídas.",
        "A base inicial é idêntica para todos os casos; processos são recriados, sem aquecimento dedicado, e a ordem dos modos alterna entre rodadas. Carga mista: 50% de probabilidade para cada operação, com contagens efetivas aleatórias.",
        "Medições locais feitas em sessões diferentes; as datas estão registradas em results.json. A variação do computador pode influenciar os resultados; as médias não demonstram as garantias de consistência.",
        "medias.json inclui média, desvio-padrão, mínimo, máximo e N de cada métrica. Também inclui operações totais divididas pelo tempo total (pooled_ops_sec), que difere da média aritmética de ops/s.",
    ]
    md = ["# Médias dos benchmarks", "", description, "", markdown_table(compact_headers, compact_rows),
          "", "## Detalhamento por cenário", "", markdown_table(headers, rows), "",
          "## Como interpretar", "", *("- " + note for note in notes), "",
          "[Resultados individuais](comparacao.md) · [Médias em JSON](medias.json)", ""]
    (directory / "medias.md").write_text("\n".join(md), encoding="utf-8")
    (directory / "medias.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    notes_html = "".join(f"<li>{html.escape(note)}</li>" for note in notes)
    page = ("<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Médias dos benchmarks</title><style>"
            "body{font:16px system-ui;margin:40px;background:#f4f6fa;color:#182437}"
            "p,li{line-height:1.65;max-width:1100px}h1{font-size:30px}h2{margin-top:36px}"
            ".table{overflow:auto;background:white;border:1px solid #dce2ec;border-radius:12px}"
            "table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}"
            "th,td{padding:14px;text-align:right;border-bottom:1px solid #e5e9ef;white-space:nowrap}"
            "th{background:#172d4d;color:white}td:first-child,th:first-child{text-align:left}"
            "tr:nth-child(even){background:#f0f4f9}</style></head><body>"
            f"<h1>Médias dos benchmarks</h1><p>{html.escape(description)}</p>"
            + html_table(compact_headers, compact_rows)
            + "<h2>Detalhamento por cenário</h2>" + html_table(headers, rows)
            + f"<h2>Como interpretar</h2><ul>{notes_html}</ul>"
            + "<p><a href='comparacao.html'>Resultados individuais</a> · "
            "<a href='medias.md'>Tabela em Markdown</a> · <a href='medias.json'>Médias em JSON</a></p>"
            "</body></html>")
    (directory / "medias.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="pasta com results.json e métricas brutas")
    args = parser.parse_args()
    data = aggregate(args.directory)
    write_report(args.directory, data)
    print(f"Verificadas {data['verified_runs']} execucoes. Medias: {args.directory / 'medias.html'}")


if __name__ == "__main__":
    main()

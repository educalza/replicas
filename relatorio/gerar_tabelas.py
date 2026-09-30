"""Confere os resultados existentes e gera os anexos LaTeX, sem novo benchmark."""
from pathlib import Path
import collections
import hashlib
import json
import sys
import statistics

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))
from run_benchmarks import summarize, parse_metrics

OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "benchmarks/results/20260928-173611"


def number(value):
    return "---" if value is None else f"{value:.2f}".replace(".", ",")


def escape(value):
    return str(value).replace("_", r"\_").replace("%", r"\%")


def table(headers, rows, caption, long=False):
    columns = "l" * len(headers)
    lines = [r"\begingroup\small\setlength{\tabcolsep}{4pt}"]
    if long:
        lines += [r"\begin{longtable}{" + columns + "}",
                  r"\caption{" + caption + r"}\\", r"\toprule",
                  " & ".join(headers) + r"\\\midrule\endfirsthead",
                  r"\toprule", " & ".join(headers) + r"\\\midrule\endhead",
                  r"\bottomrule\endfoot"]
    else:
        lines += [r"\begin{table}[htbp]\centering", r"\caption{" + caption + "}",
                  r"\begin{tabular}{" + columns + "}", r"\toprule",
                  " & ".join(headers) + r"\\\midrule"]
    lines += [" & ".join(map(str, row)) + r"\\" for row in rows]
    lines += ([r"\end{longtable}"] if long else
              [r"\bottomrule\end{tabular}\end{table}"])
    lines += [r"\endgroup", ""]
    return "\n".join(lines)


def main():
    raw = json.loads((SOURCE / "results.json").read_text(encoding="utf-8"))
    saved = json.loads((SOURCE / "medias.json").read_text(encoding="utf-8"))
    runs = raw["results"]
    expected = {(n, p, m) for n in range(1, 11) for p in ("leitura", "escrita", "misto")
                for m in ("strong", "eventual", "ryw")}
    assert len(runs) == 90 and {(r["round"], r["profile"], r["mode"]) for r in runs} == expected
    external = 0
    for r in runs:
        computed = summarize(r["metrics"])
        assert all(r[k] == v for k, v in computed.items()), "Métricas incorporadas divergentes"
        assert r["total"] == 1000 and r["convergence"]["converged"]
        assert r["convergence"]["records"] == 1000
        path = SOURCE / f"{r['round']}-{r['profile']}-{r['mode']}" / "metrics.txt"
        if path.exists():
            assert summarize(parse_metrics(path)) == computed, str(path)
            external += 1
    assert raw["metadata"] == saved["metadata"]
    for s in saved["summary"]:
        group = [r for r in runs if (r["profile"], r["mode"]) == (s["profile"], s["mode"])]
        assert s["n"] == len(group) == 10
        for key, actual in s["statistics"].items():
            values = ([r["convergence"]["wait_seconds"] for r in group] if key == "convergence_seconds"
                      else [r[key] for r in group if r[key] is not None])
            stats = {"n": len(values), "mean": statistics.mean(values) if values else None,
                     "sample_sd": statistics.stdev(values) if len(values) > 1 else None,
                     "min": min(values) if values else None, "max": max(values) if values else None}
            assert actual == stats, (s["profile"], s["mode"], key)
        total = sum(r["total"] for r in group)
        ok = sum(r["ok"] for r in group)
        errors = sum(r["errors"] for r in group)
        duration = sum(r["runtime_seconds"] for r in group)
        assert (s["total_operations"], s["total_ok"], s["total_errors"]) == (total, ok, errors)
        assert s["error_rate_percent"] == 100 * errors / total
        assert s["pooled_ops_sec"] == total / duration
        assert s["successful_ops_sec"] == ok / duration
    data = saved
    current_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                      for name in data["metadata"]["source_sha256"]}
    summaries = data["summary"]
    lookup = {(s["profile"], s["mode"]): s for s in summaries}
    profiles = ("leitura", "escrita", "misto")
    modes = ("strong", "eventual", "ryw")
    def mean(s, key):
        return number(s["statistics"][key]["mean"])
    main_tables = []
    rows = []
    for mode in modes:
        values = []
        for profile in profiles:
            stats = lookup[profile, mode]["statistics"]["ops_sec"]
            values.append(number(stats["mean"]) + r" $\pm$ " + number(stats["sample_sd"]))
        rows.append([mode, *values, sum(lookup[p, mode]["total_errors"] for p in profiles)])
    main_tables.append(table(["Modo", "Leitura (ops/s)", "Escrita (ops/s)", "Misto (ops/s)", "Erros"],
                             rows, "Throughput: média e DP de dez rodadas; erros em 30.000 operações por modo."))
    main_tables.append(table(["Carga", "Modo", "Tempo (s)", "Espera (s)", "Erros", r"Erros (\%)"],
        [[s["profile"], s["mode"], mean(s, "runtime_seconds"), mean(s, "convergence_seconds"),
          s["total_errors"], number(s["error_rate_percent"])] for s in summaries],
        "Tempo médio medido, espera posterior média e erros em 10.000 operações por cenário."))
    main_tables.append(table(["Carga", "Modo", "L média", "L p95", "E média", "E p95"],
        [[s["profile"], s["mode"], *[mean(s, k) for k in
          ("read_mean_ms", "read_p95_ms", "update_mean_ms", "update_p95_ms")]] for s in summaries],
        "Latências em ms: médias entre rodadas. L = leitura; E = escrita. Traço indica operação ausente."))
    main_tables.append(r"\clearpage")
    (OUT / "tabelas_resultados.tex").write_text("\n".join(main_tables), encoding="utf-8")

    appendix = ["As tabelas abaixo mostram os resultados de cada rodada. "
                "Nas 90 execuções, a verificação final encontrou as três réplicas iguais. "
                "Um tempo arredondado para 0,00 s ainda pode ter sido maior que zero."]
    ordered = sorted(raw["results"], key=lambda r: (profiles.index(r["profile"]),
                     modes.index(r["mode"]), r["round"]))
    for profile in profiles:
        runs = [r for r in ordered if r["profile"] == profile]
        title = {"leitura": "Testes de leitura", "escrita": "Testes de escrita", "misto": "Testes mistos"}[profile]
        appendix.append(r"\subsection{" + title + "}")
        appendix.append(table(["Modo", "Rodada", "ops/s", "Tempo (s)", "OK", "Erros", "Espera (s)"],
            [[r["mode"], r["round"], number(r["ops_sec"]), number(r["runtime_seconds"]), r["ok"],
              r["errors"], number(r["convergence"]["wait_seconds"])] for r in runs],
            "Resultados individuais: " + profile + ".", long=True))
        appendix.append(table(["Modo", "Rodada", "L média", "L p95", "E média", "E p95"],
            [[r["mode"], r["round"], *[number(r[k]) for k in
              ("read_mean_ms", "read_p95_ms", "update_mean_ms", "update_p95_ms")]] for r in runs],
            "Latências por rodada em ms: " + profile + ".", long=True))
    (OUT / "tabelas_por_rodada.tex").write_text("\n".join(appendix), encoding="utf-8")
    appendix.append(r"\subsection{Estatísticas por cenário}")
    labels = {"ops_sec": "Throughput (ops/s)", "runtime_seconds": "Tempo (s)",
              "read_mean_ms": "Leitura média (ms)", "read_p95_ms": "p95 leitura (ms)",
              "update_mean_ms": "Escrita média (ms)", "update_p95_ms": "p95 escrita (ms)",
              "errors": "Erros por rodada", "convergence_seconds": "Espera (s)"}
    for s in summaries:
        appendix.append(table(["Métrica", "N", "Média", "DP", "Mínimo", "Máximo"],
            [[labels[k], v["n"], *[number(v[f]) for f in ("mean", "sample_sd", "min", "max")]]
             for k, v in s["statistics"].items() if v["n"]],
            "Estatísticas: " + s["profile"] + " / " + s["mode"] + ".", long=True))
    appendix.append(r"\subsection{Taxas calculadas pelo tempo total}")
    appendix.append("A taxa total é o número de operações das dez rodadas dividido pela soma dos tempos. "
                    "A taxa OK faz a mesma conta, mas considera apenas as operações que deram certo. "
                    "As duas contas deixam de fora a espera pela sincronização depois do teste. "
                    "Elas são diferentes de somar as taxas de cada rodada e tirar a média.")
    appendix.append(table(["Carga", "Modo", "Operações", "OK", "Taxa total", "Taxa OK"],
        [[s["profile"], s["mode"], s["total_operations"], s["total_ok"], number(s["pooled_ops_sec"]),
          number(s["successful_ops_sec"])] for s in summaries], "Taxas agregadas em ops/s.", long=True))
    appendix.append(r"\subsection{Tipos de resposta nos testes}")
    status_rows = []
    for profile in profiles:
        for mode in modes:
            counts = collections.Counter()
            for r in ordered:
                if (r["profile"], r["mode"]) == (profile, mode):
                    counts.update(r["status_counts"])
            status_rows.extend([profile, mode, escape(k), v] for k, v in sorted(counts.items()))
    appendix.append(table(["Carga", "Modo", "Operação / retorno", "Contagem"], status_rows,
                          "Retornos YCSB somados nas dez rodadas de cada cenário.", long=True))
    (OUT / "apendice_resultados.tex").write_text("\n".join(appendix), encoding="utf-8")
    provenance = [f"Nesta cópia do projeto, foram conferidos {external} arquivos separados de métricas "
                  "e os resumos das 90 execuções contra as métricas incorporadas no results.json. "
                  "Todas as estatísticas das tabelas foram recalculadas e comparadas ao medias.json. "
                  "Os arquivos separados das rodadas restantes não estão disponíveis nesta cópia. "
                  "A convergência é a registrada pelo experimento, não uma nova comparação dos arquivos de dados.",
                  "Os hashes SHA-256 registrados no experimento são:"]
    for name, digest in data["metadata"]["source_sha256"].items():
        provenance.extend([r"\par\noindent\texttt{" + escape(name) + "}:",
                           r"\begin{quote}\footnotesize\texttt{" + digest[:32] +
                           r"\allowbreak " + digest[32:] + r"}\end{quote}"])
    provenance.append("Os arquivos atuais têm os hashes abaixo. Eles diferem dos registrados "
                      "no experimento, inclusive após normalizar as quebras de linha. Assim, a descrição "
                      "da implementação refere-se aos fontes atuais, enquanto os números se referem "
                      "à execução histórica. Não foi possível assegurar identidade entre as duas versões "
                      "somente com os artefatos disponíveis; essa limitação deve acompanhar a interpretação "
                      "das explicações de desempenho.")
    for name, digest in current_hashes.items():
        provenance.extend([r"\par\noindent\texttt{" + escape(name) + "} atual:",
                           r"\begin{quote}\footnotesize\texttt{" + digest[:32] +
                           r"\allowbreak " + digest[32:] + r"}\end{quote}"])
    provenance.extend([r"\noindent Hash da base inicial registrado no experimento:",
                       r"\begin{quote}\footnotesize\texttt{" + data["metadata"]["baseline_sha256"][:32] +
                       r"\allowbreak " + data["metadata"]["baseline_sha256"][32:] + r"}\end{quote}"])
    (OUT / "proveniencia.tex").write_text("\n".join(provenance), encoding="utf-8")
    print(f"Conferidos {len(raw['results'])} casos incorporados, {external} arquivos brutos e estatísticas; hashes documentados; LaTeX gerado.")


if __name__ == "__main__":
    main()

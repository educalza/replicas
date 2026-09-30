# Relatório em LaTeX

O documento explica a implementação de eventual e RYW e apresenta três
tabelas comparativas dos benchmarks, com explicações dos resultados e do
tempo maior do strong. As tabelas individuais por rodada ficam no final do PDF.

Na raiz do projeto, confira as métricas brutas e gere as tabelas:

```powershell
python relatorio/gerar_tabelas.py
```

Na pasta `relatorio`, compile duas vezes:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error relatorio.tex
pdflatex -interaction=nonstopmode -halt-on-error relatorio.tex
```

No Overleaf, envie `relatorio.tex`, `conteudo_relatorio.tex` e
`tabelas_por_rodada.tex`; selecione `relatorio.tex`
como documento principal. O script Python não é necessário para compilar.
O gerador também atualiza `tabelas_por_rodada.tex`, usado na seção final.

Os dados vêm de `benchmarks/results/20260928-173611`. O gerador valida as 90
medições contra as métricas incorporadas no `results.json` e confere os
`metrics.txt` disponíveis (apenas os nove casos da primeira rodada nesta cópia).
Também recalcula as estatísticas, compara com `medias.json` e confere os hashes
dos servidores. Não executa novos benchmarks nem verifica novamente as bases.

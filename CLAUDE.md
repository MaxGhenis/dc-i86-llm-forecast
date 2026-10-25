# CLAUDE.md

Independent agentic forecasts of DC Initiative 86, pooled through the causal map in `graph/graph.yaml`.
Read `README.md` first.

- Logged runs are append-only. Never edit `runs/*/response.md`, `response.json` or `meta.json` after a
  run is collected; add a new run instead. Pre-registered hashes and timestamps live in `prereg/`.
- Changing `graph/graph.yaml`, `context/` or `src/i86/prompt.py` changes the prompt. Regenerate it with
  `.venv/bin/i86 prompt`, commit it, and never pool runs made with different prompt hashes.
- Never copy an answer into `runs/` while any run is still going; `i86 collect` enforces this. A run
  dispatched after answers are in `runs/` must be `--late`, and the report flags it.
- Tests: `.venv/bin/pytest -q` (at most 4 workers). Test responses are MOCK and must stay labelled.
- The forecasts are model outputs under stated scenarios. Do not describe them as observations or the
  cutoff contrast as an observed causal effect.

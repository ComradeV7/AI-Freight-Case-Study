# FreightTiger Smart Assistant — Shipping-Cost Watchdog

Detects route-weeks where freight **cost per tonne-km** is rising abnormally,
decides whether a real-world note justifies it, and explains every verdict in
plain English. Built for the FreightTiger 24-hour Software Engineering Intern (AI) case study.

**Result in one line:** 11 flagged route-weeks (3 justified by notes, 8 unexplained),
**0 fabrications**, bit-identical across three clean runs (replay mode), with a full token/cost log —
plus a grounded Q&A copilot and an executive ₹-impact report.

---

## 1. What it does (brief → feature)

| Brief requirement | Implementation |
|---|---|
| Group by route + `route_type`, weekly `cost_per_tonne_km` | `src/weekly.py` (Monday–Sunday weeks; pooled weekly ratio) |
| `vs_own_history` = trailing 8-week rolling average, strictly prior weeks | `src/baselines.py` (`add_own_history`) |
| `vs_similar_routes` = same week, same `route_type`, other routes only | `src/baselines.py` (`add_peer_avg`) |
| Flag routes rising out of the ordinary | `src/flagging.py` (rising **and** `pct_vs_history ≥ t_own`, default 8%) |
| Use notes (RAG) to check for a real reason | `src/retrieval.py` (bge-small + Chroma) + `src/gate.py` (rule gate) |
| Plain-English, grounded explanation per flag | `src/explain.py` + `src/llm_client.py` (validated, cache-fallback) |
| **Stretch:** ask questions in plain English | `src/qa.py` (grounded procurement copilot) |
| Trust / eval / reproducibility / cost | `eval/`, `run_3x.*`, `logs/COST_LOG.json` |

## 2. Deliverables (what to look at)

| File | What it is |
|---|---|
| `outputs/flagged_routes.csv` | **Graded output** — 11 rows, exact 8-column contract from `sample_output_format_v2.csv` |
| `outputs/all_weeks_grid.csv` | All 728 route-weeks with raw numeric values (for auditing) |
| `outputs/gate_audit.json` | Per-candidate, per-note scope/window/polarity trace |
| `outputs/retrieval_trace.jsonl` | Retrieved notes per candidate (observability only) |
| `outputs/eval_report.md` | Accuracy, citation, fabrication, audit, mutation, ablation results |
| `outputs/REPRO.md` | 3-run SHA-256 hashes + temp-0 vs temp-0.7 diff |
| `outputs/business_insights.md` | ₹ financial triage, transporter drilldown, slow-creep discovery |
| `logs/COST_LOG.json` | LLM calls, in/out tokens, cost for one full run |

## 3. Quick start

Prerequisites: **Python 3.10+**. This project uses [uv](https://docs.astral.sh/uv/).

```bash
cd freighttiger
uv venv .venv
uv pip install -r requirements.txt
.venv\Scripts\activate            # Windows PowerShell;  source .venv/bin/activate on macOS/Linux
```

*(Plain `python -m venv .venv` + `pip install -r requirements.txt` also works.)*
`requirements-ai.txt` is optional and only for experimenting with alternative vector stores.

## 4. Run the whole assignment (end-to-end)

```bash
# 1. Full pipeline (offline; instant, deterministic, no API key needed)
python src/main.py
#    -> outputs/flagged_routes.csv, all_weeks_grid.csv, gate_audit.json, retrieval_trace.jsonl

# 2. Tests (unit + eval + QA)
python -m pytest -q

# 3. Trust: evaluation report
python eval/generate_report.py            # -> outputs/eval_report.md

# 4. Executive business insights
python src/insights.py                     # -> outputs/business_insights.md

# 5. Stretch-goal Q&A copilot
python src/qa.py "Why did Chennai-Bangalore get pricier in March and which transporters drove it?"

# 6. Reproducibility + cost (3 clean runs, then one at temp 0.7)
.\run_3x.ps1                               # Windows PowerShell
# ./run_3x.sh                              # macOS / Linux / WSL
```

The pipeline is **offline by default**: explanations resolve from the cache
(`data/llm_cache.json`) and fall back to a deterministic template; the network is
never touched unless `--live` is passed. So step 1 works on a machine with **no
API key and no LLM running**.

### Optional: live LLM explanations

The committed cache already contains real LLM reasons, so this is only needed to
regenerate them. Pick the syntax for **your** shell (they differ!):

```powershell
# PowerShell
$env:LLM_PROVIDER = "ollama"      # local, free, open-source model
$env:OLLAMA_MODEL = "llama3.2:3b"
python src/main.py --live

$env:LLM_PROVIDER = "openai"      # Groq / OpenAI-compatible hosted
$env:LLM_API_KEY  = "gsk_your_key_here"
$env:OPENAI_MODEL = "openai/gpt-oss-120b"
python src/main.py --live
```

```bat
:: cmd.exe
set LLM_PROVIDER=ollama
set OLLAMA_MODEL=llama3.2:3b
python src\main.py --live

set LLM_PROVIDER=openai
set LLM_API_KEY=gsk_your_key_here
set OPENAI_MODEL=openai/gpt-oss-120b
python src\main.py --live
```

```bash
# bash (macOS / Linux / WSL)
export LLM_PROVIDER=ollama OLLAMA_MODEL=llama3.2:3b
python src/main.py --live

export LLM_PROVIDER=openai LLM_API_KEY=gsk_your_key_here OPENAI_MODEL=openai/gpt-oss-120b
python src/main.py --live
```

If the LLM is unreachable or its answer fails validation, the pipeline prints one
notice and falls back to the template — **it never crashes and never changes a verdict**.

## 5. How it works (pipeline stages)

`python src/main.py` runs, in order:

| Stage | Module | Output |
|---|---|---|
| Load + validate shipments | `src/load.py` | route, `week_of` (Monday) |
| Weekly pooled cost/tonne-km | `src/weekly.py` | one row per route-week |
| Own-history + peer baselines | `src/baselines.py` | `pct_vs_history`, `pct_vs_peers` |
| Candidates | `src/flagging.py` | rising & above threshold |
| Notes registry (curated + dynamic) | `src/notes.py` | scope/window/polarity |
| Rule gate | `src/gate.py` | `flagged`, `matched_note_id`, trace |
| Retrieval trace | `src/retrieval.py` | semantic top-3 per candidate |
| Explanations | `src/explain.py` | grounded `reason` per row |
| Write deliverables | `src/output.py` | the two CSVs |

### Baselines, precisely

- **`vs_own_history`** — the route's **trailing 8-week rolling mean** of the weekly
  ratio, using only weeks **strictly before** the current week. Fewer than 8 prior
  weeks → use all available (7 first-weeks have no prior history and are excluded).
- **`vs_similar_routes`** — the **unweighted mean** of the *other* routes' weekly
  ratios in the same week and same `route_type` (self excluded).
- **Candidate rule** — `pct_vs_history > 0` **and** `pct_vs_history ≥ t_own` (default 8%).

### The gate (how a rise is justified)

A `No (justified)` verdict requires a note that (a) applies to the route (or
`All Routes`), (b) overlaps the week Mon–Sun, and (c) has `polarity = causes_rise`.
Ties break: route-specific over `All Routes`, then earliest `effective_from`, then
lowest note id. No matching note → `Yes` (unexplained). Verdicts come **only** from
this deterministic rule gate — never from the LLM.

## 6. AI: retrieval + grounded explanations

- **Retrieval (RAG):** `sentence-transformers` `BAAI/bge-small-en-v1.5` + ChromaDB
  index the notes; the trace records the top-3 per candidate. Retrieval is
  observability only — it does **not** decide verdicts (see the ablation in
  `outputs/eval_report.md`: it keeps an off-window note in the top-3 that the gate
  correctly rejects).
- **Explanation resolution order:** `cache → live (only with --live) → deterministic
  template`. Live answers are **validated against a FACTS block** (note ids, dates,
  numbers) before being accepted or cached; invalid answers are discarded and the
  template is used. The LLM sees only `route`, `week_of`, the verdict, and note
  metadata — it never sees or sets the verdict or `matched_note_id`.

## 7. Trust: how we checked it

| Check | Result |
|---|---|
| Verdict accuracy vs 11 hand labels | **11 / 11** |
| Cited-note exact match | **3 / 3** |
| Fabrications (must be 0) | **0** |
| Numeric fields vs the 3 sample rows | **9 / 9** |
| Independent audit vs `context_notes.csv` (route/window/cost-rise) | **3 / 3 pass** |
| Mutation tests (date shift, route swap, no-effect text) | **9 / 9 flip to unexplained** |
| Retrieval-only ablation (wrong-window trap) | correct gate verdict; retrieval alone insufficient |

Reproduce all of it: `python eval/generate_report.py`.

## 8. Reproducibility & cost

**Reason provenance for the committed `outputs/flagged_routes.csv`:** all 11 reasons
are **LLM-written** (Groq `openai/gpt-oss-120b`, temperature 0, seed 42), **0 template
fallbacks**, and are reproducible from the committed cache `data/llm_cache.json` —
`python src/main.py` (no key, no network) replays them (three runs, SHA-256
`E73E85A7…`, identical). `run_3x.*` separately shows the live behaviour: three clean
temp-0 runs and one temp-0.7 run, where only the *reason wording* varies.

One full cold-cache run (`logs/COST_LOG.json`):

| Metric | Value |
|---|---:|
| LLM calls | 11 |
| Input tokens | 3,710 |
| Output tokens | 1,079 |
| Local cost (Ollama) | $0.0000 |
| Hosted-equivalent cost | $0.007284 |

The hosted-equivalent uses the published Groq rate in `config/pricing.yaml`
(`qwen/qwen3.8-27b`: $0.80 / $4.00 per 1M in/out, source + date recorded there).
Reproducibility notes: replay-from-cache is bit-identical; **live** output is
reproducible on the *same machine and model version* (a different GPU/CPU, package
version, or Ollama build can change wording even at temperature 0). The structured
columns (`route … matched_note_id`) are identical across temp 0 **and** 0.7.

## 9. Stretch goal: Procurement Copilot + Business Insights

Additive; **neither touches `outputs/flagged_routes.csv`**.

**Q&A copilot** (`src/qa.py`) — deterministic and grounded by design; answers only
from verified results, cites note ids only from `matched_note_id`, and refuses
anything it cannot ground:

```bash
python src/qa.py "Why did Chennai-Bangalore get pricier in March and which transporters drove it?"
python src/qa.py "what happened on Ahmedabad-Mumbai in January 2025?"
python src/qa.py "why did costs rise on Hyderabad-Bangalore?"   # -> clean refusal
```

**Executive insights** (`src/insights.py` → `outputs/business_insights.md`):

| Bucket | Weeks | Excess (INR, vs 8-wk baseline) |
|---|---:|---:|
| Justified surge spend | 3 | ₹77,960 |
| Unexplained financial leakage | 8 | ₹1,08,463 |
| **Total** | **11** | **₹1,86,423** |

- **Transporter drilldown:** each flagged week is split by carrier vs that carrier's
  own trailing-8-week average. E.g. Delhi-Jaipur 2024-11-11 is *corridor-wide* (all
  three carriers ~+33–37% together; **no note explains it**), and Chennai-Bangalore
  2025-03-17 is *unexplained* with every carrier still above its trailing average
  (Speedway Logistics +23.3% and Trident Carriers +20.7% highest). These are
  descriptions of the data, not asserted causes. The file has **6 transporters**
  (`Coromandel Carriers` only appears on Delhi-Chennai).
- **Slow-creep discovery:** first-8-weeks-2024 vs last-8-weeks-2025 shows six routes
  drifting −2%…+7%, but **Mumbai-Pune +28.6%** (3.34 → 4.29 INR/tonne-km). A trailing
  8-week baseline absorbs slow creep into itself (median ~+1%/week on Mumbai-Pune since
  mid-2025), so the required window only trips twice — a real procurement blind spot the
  report calls out with a long-horizon recommendation.

## 10. Configuration & CLI

**`config/params.yaml`** — `flagging`: `t_own: 0.08`, `t_peer: 0.15`, `history_window: 8`;
`llm`: provider/model/base_url/temperature(0)/seed(42)/… The API key is **never** stored here.

**`src/main.py` flags**

| Flag | Default | Meaning |
|---|---|---|
| `--shipments` | `data/shipment_records.csv` | shipments CSV |
| `--notes` | `data/context_notes.csv` | notes CSV |
| `--output` | `outputs/flagged_routes.csv` | main output path |
| `--threshold` | `0.08` (from params) | own-history flagging threshold |
| `--live` | off | allow live LLM calls (cache checked first) |
| `--no-cache` | off | ignore shared cache; write to a separate dir |
| `--temperature` | config | override temperature (reproducibility runs) |

**Environment variables:** `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`,
`OPENAI_MODEL`, `OLLAMA_MODEL`, `OLLAMA_TEMPERATURE`, `OLLAMA_SEED`, `IGNORE_LLM_CACHE=1`.

The pipeline is **portable**: unseen notes (new ids, edited text) are interpreted on
the fly (`src/notes.py::build_registry`), and a modified `context_notes.csv` never
crashes the gate.

## 11. Project layout

```
freighttiger/
├── config/                 notes_registry.yaml · params.yaml · pricing.yaml
├── data/                   shipment_records.csv · context_notes.csv · sample_output_format_v2.csv
├── eval/                   run_eval.py · audit_justified.py · mutation_tests.py
│                           retrieval_ablation.py · generate_report.py · labeled.csv
├── logs/                   usage.jsonl · COST_LOG.json
├── outputs/                flagged_routes.csv · all_weeks_grid.csv · gate_audit.json ·
│                           retrieval_trace.jsonl · eval_report.md · REPRO.md · business_insights.md
├── scripts/                aggregate_cost.py · compare_non_reason.py · cross_check_notes.py
├── src/
│   ├── main.py             full pipeline entry point (CLI)
│   ├── load.py             load + schema validation
│   ├── weekly.py           weekly pooled cost/tonne-km
│   ├── baselines.py        own-history + peer baselines
│   ├── flagging.py         candidate rule + sensitivity
│   ├── notes.py            curated + dynamic notes registry
│   ├── gate.py             justification rule gate (+ audit)
│   ├── retrieval.py        semantic retrieval trace (RAG)
│   ├── explain.py          grounded explanation layer
│   ├── llm_client.py       cache → live → template resolver
│   ├── output.py           deliverable CSV writers (8-column contract)
│   ├── business.py         shared analytics (₹ excess, drilldown, drift)
│   ├── insights.py         -> outputs/business_insights.md
│   └── qa.py               grounded Q&A copilot (stretch goal)
├── tests/                  unit + eval + QA tests
├── run_3x.ps1 / run_3x.sh  reproducibility harness
├── requirements.txt        core deps (UTF-8)   ·   requirements-ai.txt (optional)
├── SPEC.md                 exact definitions, contract, guardrails, design decisions
└── README.md
```

## 12. Design decisions & assumptions

- Pooled weekly ratio per route-week, then **unweighted** means for both baselines;
  all money/ratio math uses `Decimal` with `ROUND_HALF_UP`.
- **N003** (diesel) is treated as applying to the week of `2025-05-05` only.
- Output contains **only candidate rows**; non-candidates are not emitted.
- Notes are the source of truth in `config/notes_registry.yaml`; unseen/edited notes
  are derived from the CSV (scope/window/polarity) so the pipeline stays portable.
- **Thin peer groups:** `Short` and `Long` each contain only **2 routes** and `Medium`
  **3**, so excluding self leaves a **single peer** for 4 of the 7 routes (2 peers for
  the other 3). `vs_similar_routes` is therefore a one-to-one comparison on most routes
  and should be read as directional, not statistically robust.
- Ambiguities left open in the brief are recorded in `SPEC.md` (threshold direction,
  `vs_*` string format, candidate scope, decimal precision, window semantics).

## 13. LLM cross-check findings

A sanity script (`scripts/cross_check_notes.py`) asks a local model to reproduce the
note fields. On 2026-10-14, **llama3.2:3b** disagreed with the curated YAML on **28
fields** across 10 notes (hallucinated 2022/2023 dates, wrong scope, wrong polarity) —
**which is exactly why verdicts never depend on the LLM**: the model only writes prose,
and every verdict/note-id comes from the deterministic rule gate. The curated registry
remains the source of truth. Details in the script and in `SPEC.md`.

---

### TL;DR commands

```bash
python src/main.py         # produce the graded CSV (offline, deterministic)
python -m pytest -q        # 126 tests
python eval/generate_report.py   # trust report
python src/insights.py     # business ₹ insights
python src/qa.py "why did Chennai-Bangalore get pricier in March?"
.\run_3x.ps1               # reproducibility + cost
```

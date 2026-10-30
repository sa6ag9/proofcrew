# ProofCrew

**A Nemotron crew on Nebius Token Factory where no agent grades its own homework — and every run leaves proof.**

Give ProofCrew a task. A planner splits it in two, two workers execute in
parallel, an independent screener checks their work, the workers
cross-verify *each other*, and the planner adjudicates **only** if they
disagree. What you get back is the deliverable **plus a SHA-256 hash-chained
receipt file** that anyone can re-verify with a standard-library-only script
— no ProofCrew install, no network, no trust required.

Built for the **Nebius × NVIDIA Global AI Hackathon** (Track: Best Apps and
Agents).

## Why

Multi-agent systems have a quiet credibility problem: the same model that
produced an answer usually ends up vouching for it, and the run leaves no
evidence anyone else could check. ProofCrew is built around the opposite
discipline:

- **Separation of duties.** The planner never writes the work. The workers
  never review their own output — each verifies the *other's*. The screener
  produced none of it. The adjudicator is invoked only on disagreement, so
  its judgment is spent exactly where the crew actually split.
- **Conservative escalation.** An unparseable or missing peer review counts
  as disagreement and escalates. Silence never counts as agreement.
- **Proof, not promises.** Every stage appends a receipt to a hash chain:
  each receipt contains the SHA-256 of the previous one, so altering any
  stage after the fact breaks the chain detectably. The final receipt pins
  the SHA-256 of the deliverable itself.
- **Honest grounding.** Worker B grounds its part with a Tavily web search
  *when a Tavily key is configured*. When it isn't, the receipts record
  `grounded: false`. The crew never fakes a research call.

## How it works

```
                 task
                  │
        ┌─────────▼──────────┐
        │ PLAN — Nemotron 3  │  splits the task into two complementary
        │ Ultra (550B-A55B)  │  parts + a web search query
        └─────────┬──────────┘
          ┌───────┴────────┐
          ▼                ▼
   ┌─────────────┐  ┌─────────────┐
   │ WORK A      │  │ WORK B      │  two Nemotron 3 Super (120B-A12B)
   │ Nemotron 3  │  │ Nemotron 3  │  workers in parallel; B grounds its
   │ Super       │  │ Super       │  part via Tavily (receipts say if not)
   └──────┬──────┘  └──────┬──────┘
          └───────┬────────┘
        ┌─────────▼──────────┐
        │ SCREEN — Nemotron  │  independent screen of both outputs;
        │ 3 Nano (30B-A3B)   │  Nano produced none of the work
        └─────────┬──────────┘
        ┌─────────▼──────────┐
        │ CROSS-VERIFY       │  worker A verifies B's output,
        │ Super ⇄ Super      │  worker B verifies A's — never their own
        └─────────┬──────────┘
            agree │ disagree
        ┌─────────┴──────────┐
        ▼                    ▼
   assemble parts      ADJUDICATE — Ultra returns,
   untouched           resolves the dispute,
                       writes the final deliverable
                  │
                  ▼
   deliverable + receipts.jsonl (hash-chained)
```

Per run that's 6 inference calls, 7 on disagreement — three Nemotron tiers,
each doing the job its size suits: Ultra for planning/adjudication, Super
for execution and peer review, Nano for fast screening.

## How Nebius Token Factory and Nemotron are used

All inference is a **runtime call to the Nebius Token Factory API**
(`https://api.tokenfactory.nebius.com/v1/`, OpenAI-compatible chat
completions) — that is what makes ProofCrew run on Nebius. Models (IDs
configurable via environment, see `.env.example`):

| Role | Default model | Job |
|---|---|---|
| Planner / adjudicator | `nvidia/nemotron-3-ultra-550b-a55b` | Split the task; resolve cross-verification disputes |
| Workers / cross-verifiers | `nvidia/nemotron-3-super-120b-a12b` | Execute the two parts in parallel; verify each other's output |
| Screener | `nvidia/nemotron-3-nano-30b-a3b` | Fast independent screen of both outputs |

## How Tavily is used

The planner emits a search query with its plan. When `TAVILY_API_KEY` is
set, worker B's prompt includes live Tavily results for that query (title,
URL, content) with instructions to cite URLs it relies on, and its work
receipt records `grounded: true`. This is a real runtime call to the Tavily
API (`https://api.tavily.com/search`). Without a key, no call is made and
the receipt records `grounded: false` — check it yourself in the receipts.

## Setup

Requirements: Python 3.10+. One dependency: the `openai` SDK (used only to
talk to Token Factory). The web UI, Tavily client, and receipt verifier are
standard library only.

```bash
git clone https://github.com/sa6ag9/proofcrew.git
cd proofcrew
pip install -r requirements.txt

cp .env.example .env   # then fill in your keys, or export them directly
export TOKENFACTORY_API_KEY=<your Nebius Token Factory key>
export TAVILY_API_KEY=<optional, enables grounded worker B>
```

Get a Token Factory key at <https://tokenfactory.nebius.com> (billing setup
with a bank card is required to complete onboarding). A full demo run costs
well under a dollar at published Nemotron tier prices.

## Run it

Command line:

```bash
python3 run.py "Write a launch brief for a fictional coffee subscription for remote workers"
# -> prints the deliverable, writes proofcrew-out/deliverable.md
#    and proofcrew-out/receipts.jsonl, self-checks the chain
```

Web UI (stdlib `http.server`, idles in ~50 MB — happy on a 1 GB box):

```bash
python3 app.py            # http://localhost:8080  (PORT env to change)
```

Submit a task, read the deliverable, see the stage list, the grounding and
adjudication flags, the chain verdict, and download the receipts.

## Verify the receipts — don't trust, check

Every run writes `receipts.jsonl`: one JSON receipt per stage, each with
`seq`, `actor`, `kind`, `payload`, `prev_hash`, and `hash` (SHA-256 over the
canonical receipt). Verify any run, anywhere, with only Python's standard
library:

```bash
python3 verify_receipts.py proofcrew-out/receipts.jsonl
# 8 receipts: planner/plan -> worker_a/work -> worker_b/work -> ...
# worker_b grounded via Tavily: True
# CHAIN VALID — every receipt hashes to the next; nothing was altered.
```

Edit one byte of any receipt and re-run: it reports `CHAIN INVALID` and
names the broken receipt. The unit tests prove this, including the case
where an attacker recomputes the tampered receipt's own hash (the next
link still breaks).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

15 tests, no network, no API key: the hash chain (valid chain passes;
tampered payload, tampered hash, rehashed tamper, and dropped receipt all
fail), the shipped `verify_receipts.py` against real files (accepts valid,
rejects tampered), the adjudication gate (adjudicator fires only on
disagreement; unparseable reviews escalate), and grounding honesty
(`grounded: false` without a Tavily key; research text reaches worker B
with one). Test doubles live in `tests/` only — never in the shipped path.

## Project layout

```
proofcrew/
  config.py     environment configuration (keys, model IDs, base URL)
  transport.py  Token Factory transport (OpenAI-compatible)
  crew.py       the five-stage orchestration + adjudication gate
  tavily.py     Tavily search client (httpx)
  receipts.py   hash-chain receipts + verification (stdlib only)
run.py          CLI entry point
app.py          web UI entry point (stdlib http.server)
verify_receipts.py  standalone chain verifier (stdlib only)
tests/          unit tests with fake transports
```

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Nicholas Savage / Savage AI Studios.

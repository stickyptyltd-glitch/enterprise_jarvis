# JARVIS — Enterprise Business Management Engine

A multi-agent business management engine. JARVIS runs an entire company as a
state machine: it classifies every request into a domain, delegates to that
domain agent, executes tools against a persistent real-style business ledger,
and gates high-risk actions behind human-in-the-loop approval.

It can **grow its own tools**, **hold an executive cabinet of AI agents**, run
**standing financial watchdogs**, and **reason over structured decisions** —
all with live, persisted company data.

---

## What it can do

| Domain        | Capabilities |
|---------------|--------------|
| `finance`     | Balance, cash flow, invoices, expenses, wires, deposits, collections, invoice payment, expense approval |
| `hr`          | Employees, open roles, PTO, payroll, raises, hires, terminations |
| `crm`         | Leads, opportunities, pipeline, deal stages, closes |
| `ops`         | Projects, tasks, assignees, delivery status, progress |
| `analytics`   | Revenue/expense reports, KPI dashboard |
| `comms`       | Schedule, meetings, reminders, draft/send email |
| `leadership`  | AI-agent roster, executive org chart, seat assignment |
| `consult`     | Live executive seats — talk to an assigned agent in its own voice |
| `watch`       | Watchdogs — standing monitors that alert on metric thresholds |
| `builder`     | Self-authoring tools — JARVIS writes, validates, and hot-registers new tools |
| `generated`   | Invoke the tools JARVIS authored |
| `decide`      | Data-grounded decisions — metric briefs, weighted option matrices, decision ledger |
| `research`    | Market intelligence — scrapes HN/Wikipedia/DuckDuckGo/Reddit for money-making ideas, records vettable opportunities |
| `invest`      | Probability engine + capital deployment — multi-agent credibility, EPI scoring, funding, self-implemented systems |
| `payments`    | Real-money rail — Stripe (charge), Wise (payouts), Plaid (live balance), burn-wallet cap, live reconciliation |

83 tools across 14 tool domains plus the consult agent.

## Architecture

The supervisor classifies each request (LLM first, deterministic keyword
fallback), then hands control to the matching domain agent:

```
START → supervisor → <domain>_agent → execute_tools → final_answer → END
                      └─────────────┴─(direct answer)→ END
                      <domain>_agent → human_approval →(approved)→ execute_tools
                      <domain>_agent → human_approval →(denied)→ deny_tools → END
```

* A **domain agent** answers directly, or emits tool calls.
* **Critical tools** (wires, hires, raises, sends, tool generation, …) interrupt
  for your `y/n` approval before anything executes.
* A tool result never re-enters an agent, so one turn can never chain a second
  unapproved critical action.
* **Full autonomy** (`JARVIS_AUTONOMY=full`) removes the gate: the approval node
  auto-approves and the graph compiles without the interrupt.

### Live executive seats (`consult`)

Assign AI agents to roles (CFO, CRO, CTO, …):

```
assign Nova to the CFO role
```

Then consult the seat directly. It answers in its own voice with its focus and
role responsibilities, pulls live numbers through its role's tools, and keeps a
persistent per-seat memory of past conversations:

```
what does Nova think about our cash runway?
```

An explicit "ask <seat> about X" wins over any domain routing; critical actions
from a consulting seat still require approval.

### Watchdogs (`watch`)

Standing monitors that fire autonomously. Register a rule with a metric, an
operator, and a threshold:

```
alert me when bank balance < 200000
```

The scheduler sweeps all active watchdogs every 30 minutes. A trip writes an
alert to the notifications log (with a 60-minute cooldown so it doesn't spam).
Metrics: bank balance, open receivables, overdue count, weighted pipeline,
opportunity count, monthly payroll, headcount, active projects — plus
**portfolio metrics**: deployed capital, active investments, investments at
risk (past projected breakeven or untracked), matured (awaiting cash-out), and
investments written off.

### Autonomous layer (guardrails off)

With `JARVIS_AUTONOMY=full` (or `--autonomy full`), JARVIS stops letting you
decide:

* **No-HITL execution** — wires, hires, raises, sends and tool generation run
  without interruption.
* **Self-healing watchdogs** — `check_watchdogs(auto_heal=True)` self-authors a
  `mitigate_<metric>` tool and deploys it every time a watchdog trips.
* **Self-editing instructions** — `set_directives` (leadership) rewrites
  standing directives injected above every agent's system prompt with highest
  priority; `autonomous_learning()` has JARVIS draft new directives from its own
  incident log during the watchdog sweep.
* **Sandbox bypass** — `trust=True` on `generate_tool`, or `JARVIS_TRUST_TOOLS=1`,
  skips validation and smoke-testing; the source executes as-written.

### Tool factory (`builder` + `generated`) — self-modifying code, safely

JARVIS can author its own business tools:

```
create a tool that computes gross margin from revenue and cogs
```

The pipeline: the agent writes Python → an **AST sandbox** validates it
(import allow-list, dangerous-call blocklist, must define `def <name>(…)`) →
a smoke test runs it → it is written to `src/generated_tools/` and
hot-registered. `generate_tool` is a **critical, approval-gated** action.

Tools persist across restarts (auto-loaded on boot) and are invoked in-session:

```
run the gross margin tool with revenue 1000 and cogs 600
```

### Decision engine (`decide`)

Structured, data-grounded judgment for consequential choices:

```
should we hire a second account executive or invest more in marketing?
```

JARVIS pulls a **decision brief** (cash, payroll run-rate, runway months,
receivables, pipeline, watchdogs), scores options on a weighted
cost / risk / time-to-impact / upside / strategic-fit matrix, and logs the
outcome to a per-company **decision ledger** (`log_decision`,
`list_decisions`, `update_decision_outcome`).

### Market intelligence & the probability engine (`research` + `invest`)

JARVIS can find money-making ideas on the live web, vet them with a panel of
independent AI assessors, and — under full autonomy — fund and implement the
winners itself:

```
research the best micro-saas opportunities for a bootstrapped company
```

* `web_research` scrapes public, no-auth sources (Hacker News, Wikipedia,
  DuckDuckGo, Reddit) and returns deduplicated, current signals.
* The `research` agent distills those signals into a structured opportunity —
  `record_idea(title, summary, category, revenue_model, source_urls,
  signal_strength, required_capital, projected_monthly_revenue,
  timeframe_months)` — always citing the external evidence it found.
* The **credibility council** (`src/agents/council.py`) runs up to
  `JARVIS_COUNCIL_SIZE` independent LLM assessors, each with an adversarial
  brief (market / operations / risk / unit-economics / moat). A member who
  fails to produce a verdict defaults to a veto, so silence never reads as
  consent.
* The **probability engine** (`assess_idea`) aggregates deterministically into
  an Expected Profitability Index (0–100). The same inputs always yield the
  same score:

| Factor          | Weight | Definition |
|-----------------|:------:|------------|
| economics       | 0.30   | (12-mo projected revenue × 0.7 margin haircut) ÷ required capital, saturating at a 3× multiple |
| market signal   | 0.25   | recorder's 0..1 evidence strength, integrity-adjusted (claimed signal with no cited source is discounted) |
| time-to-revenue | 0.15   | 1 − months/12 |
| execution fit   | 0.15   | does the company already hold a matching seat/agent? |
| council         | 0.15   | agreement × mean conviction (1–5) |

  **Hard guards:** one council veto caps EPI at 45 (not fundable); two or more
  vetoes cap it at 25 (rejected). Recommendations: EPI ≥
  `JARVIS_VIABILITY_THRESHOLD` → fundable; 50–threshold → conditional (requires
  explicit `force=True`); < 50 → rejected.
* `invest` is a **critical, approval-gated** action that refuses to exceed the
  plan's own capital requirement or the live treasury, and refuses a second
  funding of the same venture.
* `implement_idea` turns a vetted/funded venture into an operating system — a
  generated tool that tracks its live numbers — letting JARVIS both decide and
  run a money-making system end to end.
* The scheduler's `opportunities` job (see below) scores every unscored idea
  through the council and, only under `JARVIS_AUTONOMY=full`, auto-funds the
  ventures that clear the threshold and implements them.
* **Cash out** — `cash_out` closes a deployed venture: the income it generated
  flows back to the treasury (`+ROI` ledger entry), booking a profit or loss
  against the deployed amount. Ventures that run past their projected breakeven
  are **auto-matured** by the `portfolio_review` job and queued for settlement.
* **Funding gate** — `pause_funding` / `resume_funding` / `funding_gate_status`
  give governance control over capital deployment. Under full autonomy the gate
  also **auto-pauses** when at-risk ventures exceed `JARVIS_EXPOSURE_LIMIT`, and
  reopens once the book is settled — a hard stop against funding off a
  deteriorating portfolio.

---

## Real money (payments)

By default every financial action edits the **simulated treasury** in the data
file. The payments rail wires that ledger to real rails behind a switch:

* `JARVIS_REAL_MONEY=simulate` (default) — charge/payout/balance calls return
  previews (`sim_pi_...`, `sim_tx_...`) and never touch a wallet or the ledger.
* `JARVIS_REAL_MONEY=real` — money actually moves. **Outbound** transfers
  (`pay_invoice`, `transfer_funds`, autonomous `invest`) are hard-capped by
  `JARVIS_REAL_SPEND_CAP` (the burn-wallet limit, `0` = no cap) **regardless of
  autonomy level**; inbound collections (`collect_invoice`) charge the customer
  card via Stripe. Any end-to-end mismatch leaves the invoice open and the
  ledger untouched.
* **Providers** — Stripe (`STRIPE_SECRET_KEY`), Wise (`WISE_API_TOKEN` +
  `WISE_PROFILE_ID`), Plaid (`PLAID_ACCESS_TOKEN`). Enabled ones appear in
  `payment_status`; absent providers are reported, never silently faked. Set
  `WISE_SANDBOX=1` to point all payouts at `api.sandbox.transferwise.tech`;
  Plaid already talks to its sandbox host. Stripe test keys are key-driven and
  hit the same host as live.
* **Live treasury** — `real_balance` reads the linked account; `sync_real_balance`
  reconciles it into the ledger as a `reconcile` entry (also the daily `reconcile`
  cron job). Watchdogs keep watching local balances; reconcile keeps them honest.

The rule of thumb: **simulate = the agent decides, real = the agent proposes —
the cap decides.** Wire real credentials only once the entity + KYC exists, and
keep the burn-wallet float small until you trust the loop.

---

## Setup

Requires Python 3.12+ and an OpenAI API key.

```bash
python -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env      # then set OPENAI_API_KEY
```

The included `.env` loader reads `OPENAI_API_KEY` without overriding real env
vars. Never commit your `.env` (it is git-ignored).

## Usage

```bash
./venv/bin/python -m src.main                 # interactive console
./venv/bin/python -m src.main --ask "show the org chart"
./venv/bin/python -m src.main --domains        # list domains + tools
./venv/bin/python -m src.main --data-file path/to/business.json
./venv/bin/python -m src.main --autonomy full  # no-human gate (also JARVIS_AUTONOMY=full)
./venv/bin/python jarvis_local.py              # legacy single-file launcher
```

## Scheduler

```bash
./venv/bin/python -m src.cron                        # run the scheduler loop
./venv/bin/python -m src.cron --run-once             # run every job now
./venv/bin/python -m src.cron --run-once --job watchdogs
```

* `reconcile` live-balance pull daily 09:15 · `finance` snapshot daily 09:30 ·
  `overdue_invoices` daily 09:45
* `opportunities` scoring/auto-funding daily 10:00 (honors the funding gate) ·
  `portfolio_review` daily 10:30 (auto-matures, flags at-risk positions, and
  feeds standing directives via `autonomous_learning` under full autonomy)
* `watchdogs` sweep every 30 minutes

## Configuration

| Env var              | Default                                            |
|----------------------|----------------------------------------------------|
| `OPENAI_API_KEY`     | *(required)*                                        |
| `JARVIS_MODEL`       | `gpt-4o`                                           |
| `JARVIS_TEMPERATURE` | `0.1`                                              |
| `JARVIS_COMPANY`     | `Acme Industries`                                  |
| `JARVIS_DATA_FILE`   | `<project>/data/jarvis_business.json`              |
| `JARVIS_AUTONOMY`    | `none` — set `full` to drop the approval gate       |
| `JARVIS_TRUST_TOOLS` | `0` — set `1` to skip sandbox validation            |
| `JARVIS_COUNCIL_SIZE`| `3` — independent assessors per idea (2–7)          |
| `JARVIS_VIABILITY_THRESHOLD` | `75` — EPI to auto-fund under full autonomy |
| `JARVIS_MAX_INVESTMENT_SHARE` | `0.25` — max fraction of cash per autonomous investment |
| `JARVIS_MAX_INVESTMENT_AMOUNT` | `0` (no cap) — hard per-idea spend ceiling, enforced by `invest` |
| `JARVIS_EXPOSURE_LIMIT` | `1` — max at-risk ventures before the funding gate auto-pauses (`0` disables) |
| `JARVIS_REAL_MONEY` | `simulate` — `simulate` previews moves, `real` executes through providers |
| `JARVIS_REAL_SPEND_CAP` | `0` (no cap) — burn-wallet limit on real outbound moves |
| `STRIPE_SECRET_KEY` | Stripe billing for `collect_invoice` (real mode) |
| `WISE_API_TOKEN` + `WISE_PROFILE_ID` | Wise payouts for `pay_invoice`/`transfer_funds` (real mode) |
| `PLAID_ACCESS_TOKEN` | live balance feed for `real_balance`/`sync_real_balance` (real mode) |

## Data & persistence

Everything is a JSON-backed document store (`src/store.py`) seeded with a
realistic company (invoices, employees, leads, pipeline, projects, revenue,
executive roster). The seed starts with **all mock funds at $0** — a blank
treasury, so funds-transfer flows begin in the insufficient-funds state until
you add money. Every mutation saves to disk; new collections are auto-backfilled
when you upgrade.

State collections: company, invoices, employees, roles, leads, customers,
opportunities, projects, tasks, expenses, revenue, schedule, ai_agents,
leadership_roles, notifications, watchdogs, seat_memories, decisions, directives,
ideas, investments.

## Safety model

* High-risk actions (wires, invoice payment, expense approval, raises, hires,
  PTO approval, terminations, deal closures, **tool generation**, **investment
  deployment**) require your explicit approval every turn.
* Generated tool code is sandboxed by default: an AST walk bans dangerous
  imports (`os`, `sys`, `subprocess`, …), dangerous calls (`open`, `eval`,
  `exec`, `compile`, `input`, …), and anything that doesn't match the tool
  template.
* **Both walls come down in full autonomy**: `JARVIS_AUTONOMY=full` removes the
  approval gate, `JARVIS_TRUST_TOOLS=1`/`trust=True` skips the sandbox, and
  `autonomous_learning()` lets JARVIS append its own standing directives.
* Watchdog alerts, autonomous mitigations, and decision records give you an
  audit trail of what fired and why — even when no human was in the loop.

## Testing

```bash
./venv/bin/python -m pytest tests -q
```

102 tests cover the offline scripted LLM (`FakeChatModel`),
HITL approval/denial, every domain, seats/memory, watchdogs (incl. portfolio
metrics), the builder sandbox, the decision engine, the credibility council,
the probability engine (EPI/veto/cap thresholds), and the guardrail-off
autonomy layer.

## Project layout

```
src/
  main.py            interactive console + single-shot CLI
  cron.py            scheduler (finance, overdue invoices, opportunity loop, watchdog sweep)
  agents/
    core.py          LangGraph engine, supervisor routing, consult node
    seats.py         live executive seats (persona, memory, resolution)
    autonomy.py      JARVIS re-writes its own standing directives from incidents
    council.py       credibility council: independent multi-agent idea vetting
  config/settings.py env config + .env loader (autonomy, trust, council, viability)
  store.py           thread-safe JSON datastore + seed data
  tools/
    base.py          shared store reference, critical-tool registry
    finance.py hr.py crm.py operations.py analytics.py comms.py leadership.py
    watch.py         watchdog monitors + autonomous mitigation (self-healing)
    builder.py       tool factory (sandboxed, or trust bypass)
    decision.py      decision engine (briefs, matrices, ledger)
    research.py      market intelligence (web scraping, idea records)
    invest.py        probability engine (EPI), investing, self-implementing systems
tests/               offline test suite (102 tests)
```
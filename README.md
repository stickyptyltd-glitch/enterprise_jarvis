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
| `finance`     | Balance, cash flow, invoices, expenses, wire transfers, invoice payment, expense approval |
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

61 tools across 11 tool domains plus the consult agent.

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
opportunity count, monthly payroll, headcount, active projects.

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

* `finance` snapshot daily 09:00 · `overdue_invoices` daily 09:30
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

## Data & persistence

Everything is a JSON-backed document store (`src/store.py`) seeded with a
realistic company (invoices, employees, leads, pipeline, projects, revenue,
executive roster). Every mutation saves to disk; new collections are
auto-backfilled when you upgrade.

State collections: company, invoices, employees, roles, leads, customers,
opportunities, projects, tasks, expenses, revenue, schedule, ai_agents,
leadership_roles, notifications, watchdogs, seat_memories, decisions, directives.

## Safety model

* High-risk actions (wires, invoice payment, expense approval, raises, hires,
  PTO approval, terminations, deal closures, **tool generation**) require your
  explicit approval every turn.
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

70 tests cover routing, the offline scripted LLM (`FakeChatModel`),
HITL approval/denial, every domain, seats/memory, watchdogs, the builder
sandbox, the decision engine, and the guardrail-off autonomy layer.

## Project layout

```
src/
  main.py            interactive console + single-shot CLI
  cron.py            scheduler (finance, overdue invoices, autonomous watchdog sweep)
  agents/
    core.py          LangGraph engine, supervisor routing, consult node
    seats.py         live executive seats (persona, memory, resolution)
    autonomy.py      JARVIS re-writes its own standing directives from incidents
  config/settings.py env config + .env loader (autonomy, trust flags)
  store.py           thread-safe JSON datastore + seed data
  tools/
    base.py          shared store reference, critical-tool registry
    finance.py hr.py crm.py operations.py analytics.py comms.py leadership.py
    watch.py         watchdog monitors + autonomous mitigation (self-healing)
    builder.py       tool factory (sandboxed, or trust bypass)
    decision.py      decision engine (briefs, matrices, ledger)
tests/               offline test suite (70 tests)
```
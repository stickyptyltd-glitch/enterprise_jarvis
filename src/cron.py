"""Lightweight scheduled jobs for JARVIS.

Two entry points:
    python -m src.cron --run-once          run every job immediately, then exit
    python -m src.cron --job finance       run a single named job, then exit
    python -m src.cron                     run the scheduler loop (default daily 09:00)

The scheduler is dependency-light by design: celery/redis remain optional
accelerators; this module runs on plain asyncio so it works even when Redis
is not provisioned.
"""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Callable

from src.config.settings import Settings
from src.tools import STORE, check_balance, get_cash_flow, kpi_dashboard, list_invoices
from src.tools.watch import WATCHDOG_METRICS, check_watchdogs

WATCHDOG_SWEEP_MINUTES = 30


def job_finance_snapshot() -> str:
    parts = [check_balance(), get_cash_flow(), kpi_dashboard()]
    report = "\n\n".join(parts)
    print(f"[{datetime.now().isoformat(timespec='minutes')}] FINANCE SNAPSHOT\n{report}")
    return report


def job_overdue_invoices() -> str:
    overdue = [inv for inv in list_invoices().splitlines()[1:] if "overdue" in inv]
    if overdue:
        body = "OVERDUE INVOICES\n" + "\n".join(overdue)
        print(f"[{datetime.now().isoformat(timespec='minutes')}] {body}")
        return body
    ok = "No overdue invoices. All receivables current."
    print(f"[{datetime.now().isoformat(timespec='minutes')}] {ok}")
    return ok


def job_watchdog_sweep() -> str:
    autonomy = Settings.from_env(require_key=False).autonomy
    body = check_watchdogs(auto_heal=autonomy == "full")
    if autonomy == "full":
        from src.agents.autonomy import autonomous_learning

        body += "\n" + autonomous_learning()
    print(f"[{datetime.now().isoformat(timespec='minutes')}] WATCHDOG SWEEP\n{body}")
    return body


def job_opportunity_loop() -> str:
    """The autonomous opportunity pipeline: score every unscored idea through the
    credibility council + probability engine, then — under full autonomy — fund the
    ventures that clear the viability threshold and turn them into operating systems."""
    from src.agents.council import run_council
    from src.agents.core import create_llm
    from src.tools.invest import assess_idea, implement_idea, invest

    settings = Settings.from_env(require_key=False)
    body = f"OPPORTUNITY LOOP (autonomy={settings.autonomy or 'none'})"
    llm = create_llm(settings)
    balance = STORE.data["company"]["bank_balance"]

    at_risk = WATCHDOG_METRICS["investments_at_risk"](STORE.data)
    gate = STORE.data.get("funding_gate")
    gate = gate if isinstance(gate, dict) else {}
    limit = settings.exposure_limit
    if limit and not gate.get("paused") and at_risk > limit:
        STORE.data["funding_gate"] = {
            "paused": True,
            "at": datetime.now().isoformat(timespec="minutes"),
            "reason": f"{at_risk} investment(s) at risk exceeds allowed exposure {limit}",
        }
        STORE.notify(
            f"Funding gate AUTO-PAUSED: {at_risk} venture(s) at risk exceed exposure limit {limit}. "
            "Settle the book before deploying more capital."
        )
        STORE.save()
        body += f"\n  FUNDING AUTO-PAUSED — {at_risk} investment(s) at risk > exposure limit {limit}"
        gate = STORE.data["funding_gate"]
    elif gate.get("paused") and at_risk <= limit:
        STORE.data["funding_gate"] = {
            "paused": False,
            "at": datetime.now().isoformat(timespec="minutes"),
            "reason": "risk cleared",
        }
        STORE.notify("Funding gate reopened — no ventures at risk.")
        STORE.save()
        body += "\n  funding gate reopened (risk cleared)"
        gate = STORE.data["funding_gate"]

    unscored = [i for i in STORE.data["ideas"] if i["status"] == "proposed" and not i.get("assessment")]
    for idea in unscored:
        try:
            council = run_council(idea, llm, size=settings.council_size)
            verdict = assess_idea(idea["id"], council)
            body += f"\n  scored {idea['id']}: " + verdict.splitlines()[1].strip()
        except Exception as exc:
            body += f"\n  council failed for {idea['id']}: {exc}"

    pending = [i for i in STORE.data["ideas"] if i["status"] == "vetted"]
    if settings.autonomy != "full":
        if pending:
            body += "\n  {}. awaiting owner approval to fund (JARVIS_AUTONOMY != full)".format(
                ", ".join(i['id'] for i in pending)
            )
    else:
        if gate.get("paused"):
            body += f"\n  funding paused — gate closed ({gate.get('reason', 'no reason recorded')})"
        for idea in pending:
            if gate.get("paused"):
                break
            assessment = idea.get("assessment") or {}
            if assessment.get("epi", 0) < settings.viability_threshold:
                continue
            cap_amount = settings.max_investment_amount or float("inf")
            amount = min(
                idea.get("required_capital", 0),
                balance * settings.max_investment_share,
                cap_amount,
            )
            if amount <= 0:
                body += f"\n  {idea['id']}: no capital available to deploy"
                continue
            try:
                outcome = invest(idea["id"], amount)
                balance = STORE.data["company"]["bank_balance"]
                body += f"\n  {idea['id']}: {outcome.splitlines()[0]}"
                body += "\n  " + implement_idea(idea["id"], description=f"autonomous system for {idea['title']}", execute=True).splitlines()[-1]
            except Exception as exc:
                body += f"\n  {idea['id']}: funding failed ({exc})"

    print(f"[{datetime.now().isoformat(timespec='minutes')}]\n{body}")
    return body


def job_portfolio_review() -> str:
    """Review the deployed investment book: size it, auto-mature ventures past
    their projected breakeven, flag at-risk positions, and — under full autonomy —
    fold the findings into the standing directives via autonomous_learning."""
    data = STORE.data
    deployed = WATCHDOG_METRICS["portfolio_deployed"](data)
    active = WATCHDOG_METRICS["active_investments"](data)
    at_risk_snapshot = WATCHDOG_METRICS["investments_at_risk"](data)
    written_off = WATCHDOG_METRICS["investments_written_off"](data)
    matured = WATCHDOG_METRICS["investments_matured"](data)

    now = datetime.now()
    stamped = now.isoformat(timespec="minutes")
    newly_matured = []
    for inv in data.get("investments", []):
        breakeven = inv.get("breakeven_months")
        if inv.get("status") != "active" or not isinstance(breakeven, (int, float)):
            continue
        try:
            start = datetime.fromisoformat(str(inv.get("at", "")))
        except (TypeError, ValueError):
            continue
        if now - start >= timedelta(days=breakeven * 30.44):
            inv["status"] = "matured"
            inv["notes"].append({"at": stamped, "status": "matured", "note": "auto-matured at projected breakeven"})
            newly_matured.append(inv["id"])
    if newly_matured:
        matured += len(newly_matured)
        STORE.notify(
            f"PORTFOLIO REVIEW: auto-matured {', '.join(newly_matured)} (past projected breakeven). "
            "Settle them with cash_out to recover capital."
        )
        STORE.save()

    at_risk = WATCHDOG_METRICS["investments_at_risk"](data)
    lines = [
        f"PORTFOLIO REVIEW — {STORE.currency(deployed)} deployed across {active} active investment(s) | "
        f"at risk {at_risk_snapshot} | matured {matured} | written off {written_off}"
    ]
    for inv in data.get("investments", []):
        notes = len(inv.get("notes", []) or [])
        be = f"{inv.get('breakeven_months', 0):.1f} mo" if isinstance(inv.get("breakeven_months"), (int, float)) else "n/a"
        lines.append(
            f"  {inv['id']} | {inv['status']} | {STORE.currency(inv['amount'])} | breakeven {be} | progress notes: {notes}"
        )
    if at_risk:
        STORE.notify(f"PORTFOLIO REVIEW: {at_risk} investment(s) at risk (past breakeven or untracked).")
        STORE.save()
        settings = Settings.from_env(require_key=False)
        if settings.autonomy == "full":
            from src.agents.autonomy import autonomous_learning

            lines.append(
                "  standing learning: " + autonomous_learning().splitlines()[0].split(": ", 1)[-1]
            )
    report = "\n".join(lines)
    print(f"[{datetime.now().isoformat(timespec='minutes')}]\n{report}")
    return report


JOBS: dict[str, Callable[[], str]] = {
    "finance": job_finance_snapshot,
    "overdue_invoices": job_overdue_invoices,
    "watchdogs": job_watchdog_sweep,
    "opportunities": job_opportunity_loop,
    "portfolio_review": job_portfolio_review,
}

SCHEDULE: list[tuple[str, tuple[int, int]]] = [
    ("finance", (9, 0)),
    ("overdue_invoices", (9, 30)),
    ("opportunities", (10, 0)),
    ("portfolio_review", (10, 30)),
]


def _run_job_safely(job_name: str) -> None:
    try:
        JOBS[job_name]()
    except Exception as exc:
        print(f"Job {job_name} failed: {exc}")


async def scheduler_loop() -> None:
    print("JARVIS scheduler running. Ctrl+C to stop.")
    last_sweep = datetime.now()
    await asyncio.sleep(0)  # yield once so Ctrl+C registers
    while True:
        now = datetime.now()
        for job_name, (when_hour, when_min) in SCHEDULE:
            if now.hour == when_hour and now.minute == when_min:
                _run_job_safely(job_name)
        if (now - last_sweep).total_seconds() >= WATCHDOG_SWEEP_MINUTES * 60:
            _run_job_safely("watchdogs")
            last_sweep = now
        await asyncio.sleep(55)


def run_once(job: str | None = None) -> None:
    targets = [job] if job else list(JOBS)
    for job_name in targets:
        if job_name not in JOBS:
            print(f"Unknown job '{job_name}'. Available: {', '.join(JOBS)}")
            sys.exit(2)
        JOBS[job_name]()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS scheduled jobs")
    parser.add_argument("--run-once", action="store_true", help="run all jobs immediately and exit")
    parser.add_argument("--job", default=None, help="run a single job by name")
    args = parser.parse_args()

    if args.run_once or args.job:
        run_once(args.job)
        return

    try:
        asyncio.run(scheduler_loop())
    except KeyboardInterrupt:
        print("\nScheduler stopped.")


if __name__ == "__main__":
    main()
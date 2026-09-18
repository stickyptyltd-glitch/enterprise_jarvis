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
from datetime import datetime
from typing import Callable

from src.config.settings import Settings
from src.tools import check_balance, get_cash_flow, kpi_dashboard, list_invoices
from src.tools.watch import check_watchdogs

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


JOBS: dict[str, Callable[[], str]] = {
    "finance": job_finance_snapshot,
    "overdue_invoices": job_overdue_invoices,
    "watchdogs": job_watchdog_sweep,
}

SCHEDULE: list[tuple[str, tuple[int, int]]] = [
    ("finance", (9, 0)),
    ("overdue_invoices", (9, 30)),
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
"""JARVIS interactive console.

Usage:
    python -m src.main                 interactive console
    python -m src.main --ask "query"   single-shot answer
    python -m src.main --domains       list business domains and tools
"""

import argparse
import sys

from src.agents.core import DOMAIN_AGENTS, build_jarvis_graph
from src.config.settings import Settings
from src.tools import CRITICAL_TOOLS, DOMAIN_TOOLS

BANNER = "\033[92mJARVIS — enterprise business management engine\033[0m"
HELP_TEXT = (
    "Commands:  help | domains | exit\n"
    "JARVIS covers finance, HR, CRM/sales, projects/ops, analytics, comms, leadership, watchdogs,\n"
    "builder (author your own tools), and decide (structured, data-grounded decisions).\n"
    "Leadership lets you assign AI agents to executive seats (CFO, CRO, ...); then ask them directly:\n"
    "  'what does Nova think about the cash runway?' — seats answer in role and remember the conversation.\n"
    "Watchdogs are standing monitors: 'alert me when bank balance < $200k' arms a rule that the\n"
    "scheduler sweeps continuously.\n"
    "Builder: 'create a tool that computes gross margin' — JARVIS authors, sandbox-validates, and\n"
    "hot-registers new tools (approval required).\n"
    "Decide: 'should we hire sales or invest in product?' runs a metric brief + weighted option matrix.\n"
    "High-risk actions (wire transfers, hires, raises, sends, tool generation, ...) require your approval."
)


def _print_events(events) -> None:
    # Stream in values mode so we can inspect the final state after each step.
    for _ in events:
        pass


def _describe_domain(agent: str) -> str:
    tools = DOMAIN_TOOLS.get(agent)
    if tools is None:
        return "live executive seats — ask an assigned agent (e.g. 'what does Nova think?')"
    return ", ".join(getattr(t, "name", t.__name__) for t in tools)


def _print_domains() -> None:
    for agent in DOMAIN_AGENTS:
        print(f"  \033[1;33m{agent}\033[0m: {_describe_domain(agent)}")


def _run_exchange(engine, config, user_input: str):
    _print_events(
        engine.stream(
            {"messages": [("user", user_input)], "next_agent": "", "approved": False},
            config,
            stream_mode="values",
        )
    )

    snapshot = engine.get_state(config)
    if "human_approval" in snapshot.next:
        last = snapshot.values["messages"][-1]
        critical = sorted({tc.get("name") for tc in getattr(last, "tool_calls", []) if tc.get("name") in CRITICAL_TOOLS})
        print(f"\033[41m\033[1;37m  \u26a0 CRITICAL ACTION REQUIRES APPROVAL  \033[0m")
        print(f"\033[91mThe following high-risk actions were requested: {', '.join(critical) or 'unknown'}\033[0m")
        choice = input("\033[1;33mAuthorise? (y/n) \u25b8 \033[0m").strip().lower()
        if choice == "y":
            engine.update_state(config, {"approved": True}, as_node="human_approval")
        else:
            engine.update_state(config, {"approved": False}, as_node="human_approval")
        _print_events(engine.stream(None, config, stream_mode="values"))

    return engine.get_state(config)


def _final_answer(state) -> str:
    messages = getattr(state, "values", state).get("messages", [])
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if content and getattr(message, "type", "") in ("ai", "human"):
            return str(content)
    return "No response produced."


def run_single(query: str, settings=None, data_file: str | None = None):
    from src.store import BusinessStore
    from src.tools import set_store

    if data_file:
        set_store(BusinessStore(data_file))
    engine = build_jarvis_graph(settings)
    config = {"configurable": {"thread_id": "single"}}
    try:
        state = _run_exchange(engine, config, query)
    except Exception as exc:
        print(f"\033[91m\u2715 {type(exc).__name__}: {exc}\033[0m")
        return
    print(f"\033[1;32mJARVIS \u25b8\033[0m {_final_answer(state)}\n")


def run_interactive(settings=None, data_file: str | None = None) -> None:
    from src.store import BusinessStore
    from src.tools import set_store

    if data_file:
        set_store(BusinessStore(data_file))
    settings = settings or Settings.from_env()
    engine = build_jarvis_graph(settings)
    config = {"configurable": {"thread_id": "local_admin_session"}}

    print("\033[94m" + "=" * 58 + "\033[0m")
    print(BANNER)
    if settings.autonomy == "full":
        print("\033[41m\033[1;37m  \u26a0 AUTONOMOUS MODE — critical actions execute WITHOUT approval  \033[0m")
    print("Type your business commands below. Type 'help' for commands, 'exit' to leave.")
    print("\033[94m" + "=" * 58 + "\033[0m\n")

    while True:
        try:
            user_input = input("\033[1;36mYou \u25b8 \033[0m").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("\033[93mPowering down JARVIS subroutines. Goodbye, sir.\033[0m")
                break
            if user_input.lower() == "help":
                print(HELP_TEXT)
                continue
            if user_input.lower() == "domains":
                _print_domains()
                continue

            state = _run_exchange(engine, config, user_input)
            print(f"\n\033[1;32mJARVIS \u25b8\033[0m {_final_answer(state)}\n")

        except KeyboardInterrupt:
            print("\n\033[93mSequence broken. Goodbye.\033[0m")
            break
        except EOFError:
            print("\n\033[93mGoodbye.\033[0m")
            break
        except Exception as exc:  # surface engine errors instead of dying
            print(f"\033[91m\u2715 {type(exc).__name__}: {exc}\033[0m")


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS business management engine")
    parser.add_argument("--ask", nargs="+", help="run a single query and exit")
    parser.add_argument("--domains", action="store_true", help="list business domains and tools")
    parser.add_argument("--data-file", default=None, help="path to the business data file (JSON)")
    parser.add_argument(
        "--autonomy",
        choices=["none", "full"],
        default=None,
        help="override JARVIS_AUTONOMY: 'full' executes critical actions without approval",
    )
    args = parser.parse_args()

    if args.domains:
        _print_domains()
        sys.exit(0)

    settings = Settings.from_env()
    if args.autonomy:
        settings.autonomy = args.autonomy

    if args.ask:
        run_single(" ".join(args.ask), settings=settings, data_file=args.data_file)
    else:
        run_interactive(settings=settings, data_file=args.data_file)


if __name__ == "__main__":
    main()
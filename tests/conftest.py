"""Shared fixtures: an offline, scriptable LLM stub and a fresh in-memory store."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from langchain_core.messages import AIMessage, HumanMessage

os.environ.setdefault("OPENAI_API_KEY", "test-key")


class FakeAgentLLM:
    """Replicates the bound-tools chat model used inside each domain agent."""

    def __init__(self, worker):
        self.worker = worker

    def invoke(self, messages):
        message = self.worker(messages)
        message.tool_calls = message.tool_calls or []
        return message


class FakeChatModel:
    """Stands in for ChatOpenAI: classifies routes, answers, and summarises without a network."""

    agent_worker = None

    def __init__(self, classifier, calls=None):
        self.classifier = classifier              # callable(user_text) -> domain or "end"
        self.calls = calls if calls is not None else []

    def bind_tools(self, tools):
        if FakeChatModel.agent_worker is None:
            raise RuntimeError("test did not configure an agent_worker")
        return FakeAgentLLM(FakeChatModel.agent_worker)

    def invoke(self, prompt_messages):
        self.calls.append(prompt_messages)
        joined = "\n".join(str(getattr(m, "content", "")) for m in prompt_messages)
        last_user = next(
            (str(m.content) for m in reversed(prompt_messages) if isinstance(m, HumanMessage)),
            "",
        )
        if "Classify the user's request" in joined:
            agent = self.classifier(last_user)
            return AIMessage(content=f'{{"agent": "{agent}"}}')
        if "results of the executed tools" in joined:
            last_tool = next(
                (str(m.content) for m in reversed(prompt_messages) if getattr(m, "type", "") == "tool"),
                "",
            )
            return AIMessage(content=f"Summary: {last_tool}")
        return AIMessage(content=f"Direct: {last_user}")

    @classmethod
    def set_agent_worker(cls, worker):
        cls.agent_worker = worker


@pytest.fixture()
def fresh_store():
    from src.store import BusinessStore
    from src.tools import set_store

    store = BusinessStore(data_file=None)
    store.reset()
    set_store(store)
    return store


@pytest.fixture()
def engine_builder(fresh_store):
    """Build a compiled graph around the scripted fake LLM."""

    def build(classifier, worker, settings=None):
        FakeChatModel.set_agent_worker(worker)
        from src.agents.core import build_jarvis_graph

        fake = FakeChatModel(classifier=classifier)
        if settings is not None:
            return build_jarvis_graph(settings=settings, llm=fake), fake
        return build_jarvis_graph(llm=fake), fake

    return build


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    FakeChatModel.agent_worker = None

@pytest.fixture(autouse=True)
def _offline_money_env(monkeypatch):
    """Keep the suite hermetic regardless of a user's .env (JARVIS may run real-money).

    Without this, a live Stripe key plus a burn-wallet cap in .env makes
    finance/transfer assertions hit real-mode cap errors. Pin the suite to the
    offline rail and drop provider keys unless a test overrides them.
    """
    monkeypatch.setenv("JARVIS_REAL_MONEY", "off")
    monkeypatch.setenv("JARVIS_REAL_SPEND_CAP", "0")
    for key in (
        "STRIPE_SECRET_KEY",
        "WISE_API_TOKEN",
        "WISE_PROFILE_ID",
        "WISE_SANDBOX",
        "PLAID_ACCESS_TOKEN",
        "PLAID_CLIENT_ID",
        "PLAID_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)

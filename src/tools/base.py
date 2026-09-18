"""Shared store holder so audit and ledger actions stay consistent across tools."""

from src.config.settings import Settings
from src.store import BusinessStore

CRITICAL_TOOLS: set[str] = set()


class _StoreRef:
    """Fixes the store indirection so every tool module sees the same store.

    Tool modules import ``STORE`` once at import time; holding this reference
    (instead of a store snapshot) means a later ``set_store()`` — used by the
    CLI, tests, and data-file switching — is visible to all of them.
    """

    def __init__(self, initial: BusinessStore):
        self.__store = initial

    def set(self, store: BusinessStore) -> None:
        self.__store = store

    def get(self) -> BusinessStore:
        return self.__store

    def __getattr__(self, attr):
        return getattr(self.__store, attr)


STORE = _StoreRef(BusinessStore(Settings.from_env(require_key=False).data_file))


def current_store() -> BusinessStore:
    """Return the store object backing the shared reference right now."""
    return STORE.get()


def set_store(store: BusinessStore) -> None:
    """Swap the current store (used by tests and the CLI data-file option)."""
    STORE.set(store)


def register_critical(*names: str) -> None:
    CRITICAL_TOOLS.update(names)
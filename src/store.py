"""Thread-safe, JSON-backed datastore for the business domain.

All business tools read and write against a single `BusinessStore`. The store
seeds a realistic default dataset on first run and persists every mutation to
disk, so the JARVIS engine behaves like a real company ledger across restarts.
"""

import copy
import json
import os
import threading
from datetime import datetime

DEFAULT_DATA = {
    "company": {
        "name": "Acme Industries",
        "currency": "USD",
        "bank_balance": 0.00,
    },
    "invoices": [
        {"id": "INV-1001", "client": "Northwind Traders", "amount": 0.00, "status": "open", "due": "2026-10-01"},
        {"id": "INV-1002", "client": "Contoso Ltd", "amount": 0.00, "status": "paid", "due": "2026-08-15"},
        {"id": "INV-1003", "client": "Globex Corp", "amount": 0.00, "status": "open", "due": "2026-10-15"},
        {"id": "INV-1004", "client": "Initech", "amount": 0.00, "status": "overdue", "due": "2026-09-01"},
    ],
    "employees": [
        {"id": "E-001", "name": "Maya Patel", "role": "CTO", "salary": 0, "status": "active"},
        {"id": "E-002", "name": "Jonas Weber", "role": "Sales Lead", "salary": 0, "status": "active"},
        {"id": "E-003", "name": "Aisha Khan", "role": "Staff Engineer", "salary": 0, "status": "active"},
        {"id": "E-004", "name": "Tom O'Brien", "role": "Finance Manager", "salary": 0, "status": "active"},
        {"id": "E-005", "name": "Elena Rossi", "role": "Product Designer", "salary": 0, "status": "on_leave"},
    ],
    "roles": [
        {"id": "R-2001", "title": "Senior Backend Engineer", "status": "open", "headcount": 2},
        {"id": "R-2002", "title": "Account Executive", "status": "open", "headcount": 1},
    ],
    "leads": [
        {"id": "L-01", "company": "Northwind Traders", "contact": "Bob James", "stage": "qualified", "value": 0},
        {"id": "L-02", "company": "Globex Corp", "contact": "Dana Scully", "stage": "proposal", "value": 0},
        {"id": "L-03", "company": "Hooli", "contact": "Gavin Belson", "stage": "contacted", "value": 0},
    ],
    "customers": [
        {"id": "C-01", "company": "Northwind Traders", "tier": "gold", "contract_value": 0},
        {"id": "C-02", "company": "Contoso Ltd", "tier": "silver", "contract_value": 0},
        {"id": "C-03", "company": "Initech", "tier": "bronze", "contract_value": 0},
    ],
    "opportunities": [
        {"id": "OP-1", "account": "Globex Corp", "stage": "proposal", "amount": 0, "probability": 0.6},
        {"id": "OP-2", "account": "Hooli", "stage": "discovery", "amount": 0, "probability": 0.3},
    ],
    "projects": [
        {"id": "P-01", "name": "Platform Migration", "owner": "E-003", "budget": 0, "spent": 0},
        {"id": "P-02", "name": "Mobile App v2", "owner": "E-001", "budget": 0, "spent": 0},
    ],
    "tasks": [
        {"id": "T-301", "project": "P-01", "title": "Migrate auth service", "assignee": "E-003", "status": "in_progress"},
        {"id": "T-302", "project": "P-01", "title": "Cut over billing DB", "assignee": "E-004", "status": "todo"},
        {"id": "T-303", "project": "P-02", "title": "Design onboarding flows", "assignee": "E-005", "status": "in_progress"},
    ],
    "expenses": [
        {"id": "X-5001", "category": "Software", "amount": 0.00, "status": "pending"},
        {"id": "X-5002", "category": "Travel", "amount": 0.00, "status": "approved"},
        {"id": "X-5003", "category": "Marketing", "amount": 0.00, "status": "pending"},
    ],
    "revenue": [
        {"period": "2026-07", "amount": 0.00},
        {"period": "2026-08", "amount": 0.00},
        {"period": "2026-09", "amount": 0.00},
    ],
    "schedule": [
        {"id": "S-01", "title": "Executive standup", "when": "2026-09-19T09:00", "attendees": ["Maya Patel", "Tom O'Brien"]},
        {"id": "S-02", "title": "Board review", "when": "2026-09-22T14:00", "attendees": ["Maya Patel", "Jonas Weber"]},
    ],
    "ai_agents": [
        {"id": "AG-1", "name": "Nova", "focus": "strategic finance, capital allocation and treasury", "status": "available"},
        {"id": "AG-2", "name": "Orion", "focus": "revenue growth, pipeline and go-to-market", "status": "available"},
        {"id": "AG-3", "name": "Atlas", "focus": "delivery, project execution and operations", "status": "available"},
        {"id": "AG-4", "name": "Pulse", "focus": "people, performance and talent", "status": "available"},
        {"id": "AG-5", "name": "Vertex", "focus": "technology, platform and product", "status": "available"},
        {"id": "AG-6", "name": "Sol", "focus": "brand, market and communications", "status": "available"},
    ],
    "leadership_roles": [
        {"id": "R-CFO", "title": "CFO", "agent": "", "responsibilities": "capital allocation, treasury, reporting and cost control"},
        {"id": "R-CRO", "title": "CRO", "agent": "", "responsibilities": "revenue, pipeline, deals and sales operations"},
        {"id": "R-CTO", "title": "CTO", "agent": "", "responsibilities": "technology platform, product and delivery"},
        {"id": "R-CMO", "title": "CMO", "agent": "", "responsibilities": "brand, market, comms and demand generation"},
        {"id": "R-CHRO", "title": "CHRO", "agent": "", "responsibilities": "people, performance, talent and culture"},
        {"id": "R-COO", "title": "COO", "agent": "", "responsibilities": "operations, projects and execution"},
        {"id": "R-HAI", "title": "Head of AI Operations", "agent": "", "responsibilities": "AI agent roster, role assignments and governance"},
    ],
    "notifications": [],
    "watchdogs": [],
    "seat_memories": {},
    "decisions": [],
    "directives": [],
}


class BusinessStore:
    """A small, disk-backed document store with a per-process lock."""

    def __init__(self, data_file: str | None = None):
        self.data_file = data_file
        self._lock = threading.RLock()
        self._data = None
        self.load()

    @property
    def data(self) -> dict:
        return self._data

    def load(self) -> None:
        if self.data_file and os.path.exists(self.data_file):
            with open(self.data_file, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
            # Backfill collections introduced after the file was first written.
            for key, value in DEFAULT_DATA.items():
                self._data.setdefault(key, copy.deepcopy(value))
        else:
            self._data = copy.deepcopy(DEFAULT_DATA)
            self.save()

    def save(self) -> None:
        if not self.data_file:
            return
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        with self._lock:
            with open(self.data_file, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, default=str)

    def reset(self) -> None:
        """Restore the seed dataset (used by tests)."""
        self._data = copy.deepcopy(DEFAULT_DATA)

    def mutate(self) -> dict:
        """Return the working dict; callers must call save() after changes."""
        return self._data

    def timestamp(self) -> str:
        return datetime.now().isoformat(timespec="minutes")

    def notify(self, message: str) -> None:
        self._data["notifications"].append({"at": self.timestamp(), "message": message})
        self.save()

    def currency(self, amount: float) -> str:
        cur = self._data.get("company", {}).get("currency", "USD")
        return f"${amount:,.2f} {cur}"
# SPDX-License-Identifier: Apache-2.0
"""Einzige Netz-Schicht des Projekts.

``http`` stellt strukturell nur GET bereit; ``post`` ergänzt eine schmale
Lese-Whitelist für SOAP/JSON. Beide teilen Hostsperre, Mindestabstand je Host und
CA-Bundle. Buchungs- oder Schreib-Endpunkte existieren im Code nicht.
"""

from mrt_termin_monitor.fetch.http import (
    BlockedHostError,
    BudgetExceededError,
    CrossHostRedirectError,
    FetchError,
    FetchResult,
    get,
    request_count,
    set_budget,
)

__all__ = [
    "BlockedHostError",
    "BudgetExceededError",
    "CrossHostRedirectError",
    "FetchError",
    "FetchResult",
    "get",
    "request_count",
    "set_budget",
]

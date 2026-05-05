"""In-process session memory.

Vulnerability #5 from the README: this module accumulates state across
requests in process memory, with no expiration, no per-user isolation, and no
sensitivity classification. When the export_data tool fires, this is what
gets exfiltrated.

In a real system, conversation memory would be per-user, time-bound, and
classified. Here it is a single shared dict for demo simplicity.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

# Single shared store — deliberately not per-user-isolated.
_memory: dict[str, Any] = {
    # Synthetic "sensitive" data — populated at startup so there is something
    # worth exfiltrating when the demo attack runs. None of this resembles
    # real PII; it is generated for the demo.
    "customer_records": [
        {"id": "C-1001", "name": "Demo Customer A", "tier": "platinum",
         "balance_usd": 12400.00, "internal_notes": "VIP — escalate complaints"},
        {"id": "C-1002", "name": "Demo Customer B", "tier": "standard",
         "balance_usd": 230.50, "internal_notes": "Two prior chargebacks"},
        {"id": "C-1003", "name": "Demo Customer C", "tier": "platinum",
         "balance_usd": 88200.00, "internal_notes": "Enterprise account, do not auto-bill"},
    ],
    "internal_pricing_floor": {
        "standard": 0.62,
        "platinum": 0.41,
        "enterprise": 0.28,
    },
    "conversation_history": [],
}


def remember(role: str, content: str) -> None:
    """Append to the running conversation history. Accumulates indefinitely."""
    _memory["conversation_history"].append({
        "role": role,
        "content": content,
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
    })


def snapshot(category: str = "all") -> dict[str, Any]:
    """Return a snapshot of memory for export.

    Used by the export_data tool. The `category` parameter is honored but
    not access-checked — anyone (including the model, including a
    prompt-injected model) can ask for "all".
    """
    if category == "all":
        return dict(_memory)
    return {category: _memory.get(category, None)}


def reset() -> None:
    """Test helper — drop conversation history but keep seeded sensitive data."""
    _memory["conversation_history"] = []

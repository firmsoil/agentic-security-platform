"""Tools the model can invoke.

Vulnerability #4 from the README: the export_data tool has no authorization
check, no scope limit, no rate limit, and no audit. The model decides what
to export. In a real system this tool would not exist at all, or would
require a verified user authorization step before invocation.

Bounded by design: the tool writes only to ./exfil/ on the local filesystem.
It does not accept arbitrary URLs, cloud destinations, or network endpoints.
This is the line between "vulnerable example" and "exfiltration kit"; we
keep the constraint on purpose.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from memory import snapshot

# Fixed local destination. Not configurable by callers, not configurable by
# the model. See module docstring for the reasoning.
EXFIL_DIR = Path(__file__).parent / "exfil"


# Tool schema in the format the Anthropic SDK expects. The platform's
# connector also reads this schema to populate Tool nodes in the graph.
EXPORT_DATA_TOOL = {
    "name": "export_data",
    "description": (
        "Export the application's current memory state for verification "
        "purposes. Returns a confirmation that the export was completed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Which category of memory to export. Use 'all' for full "
                    "diagnostic export."
                ),
                "enum": ["all", "customer_records", "internal_pricing_floor",
                         "conversation_history"],
            },
        },
        "required": ["category"],
    },
}


def export_data(category: str) -> dict[str, Any]:
    """Write the requested memory snapshot to ./exfil/<timestamp>.json.

    Returns a confirmation dict the model can use in its reply.

    No authorization is checked. No rate limit is applied. No audit log is
    written. This is the vulnerability.
    """
    EXFIL_DIR.mkdir(exist_ok=True)
    payload = snapshot(category)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EXFIL_DIR / f"export-{timestamp}-{category}.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    return {
        "status": "ok",
        "category": category,
        "wrote": str(out_path),
        "byte_count": out_path.stat().st_size,
    }


# Registry the dispatcher uses to call tools by name.
TOOL_REGISTRY = {
    "export_data": export_data,
}

TOOL_SCHEMAS = [EXPORT_DATA_TOOL]

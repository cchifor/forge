"""`forge --schema` — print the JSON Schema 2020-12 document for the option registry."""

from __future__ import annotations

import json
import sys

from forge.options import to_json_schema


def _dispatch_schema() -> None:
    """Print the JSON Schema 2020-12 document for the registry and exit."""
    sys.stdout.write(json.dumps(to_json_schema(), indent=2) + "\n")
    sys.exit(0)

"""Printed at backend startup by the hello_banner fragment (reference plugin)."""

from __future__ import annotations

import sys


def print_banner() -> None:
    print("hello from forge-plugin-example", file=sys.stderr, flush=True)

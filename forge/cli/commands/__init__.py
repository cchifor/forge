"""Subcommand handlers for the forge CLI.

Each module exposes a top-level dispatch function consumed by
``forge.cli.main``. Dispatch functions never return on success (they
call ``sys.exit()``) to match the original monolithic CLI's contract —
the dispatcher expects failure to propagate via exceptions and success
to terminate the process.
"""

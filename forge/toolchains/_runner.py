"""Shared subprocess helper for built-in backend toolchains.

Extracted from ``forge.generator._run_backend_cmd`` so the toolchain
implementations under ``forge/toolchains/`` can reuse the exact same
Windows PATHEXT resolution + timeout + stderr-tail behavior the
generator has shipped with. Kept in a private sibling module (not in
``__init__.py``) so importers of :class:`BackendToolchain` don't pull
the ``subprocess``/``shutil`` dependencies.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from time import perf_counter

from forge.errors import ForgeError
from forge.toolchains import Check


def run_backend_cmd(
    backend_dir: Path,
    cmd: list[str],
    description: str,
    *,
    quiet: bool = False,
    required: bool = False,
    timeout_s: int = 300,
) -> Check:
    """Run a command in ``backend_dir`` and return a :class:`Check`.

    - On success (exit 0): ``status="ok"``.
    - On non-zero exit: ``status="fail"`` (and raises
      :class:`ForgeError` when ``required=True``).
    - On ``FileNotFoundError`` (tool not on PATH): ``status="skip"``
      (raises when ``required=True``).
    - On timeout: ``status="fail"`` (raises when ``required=True``).

    Prints a single-line status to stdout unless ``quiet=True``,
    preserving the interactive look-and-feel of the pre-refactor
    ``_run_backend_cmd``.

    On Windows, Python's ``subprocess`` doesn't walk ``PATHEXT`` when
    resolving bare executable names (so ``npm`` resolves but ``npm.cmd``
    doesn't). ``shutil.which`` walks PATHEXT, so we resolve up front.
    """
    resolved = shutil.which(cmd[0])
    if resolved is not None:
        cmd = [resolved, *cmd[1:]]

    start = perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        duration_ms = int((perf_counter() - start) * 1000)
        msg = f"{description} timed out ({timeout_s // 60}m)"
        if required:
            raise ForgeError(f"{msg} while running: {' '.join(cmd)}") from e
        if not quiet:
            print(f"  [!!] {msg}")
        return Check(name=description, status="fail", details=msg, duration_ms=duration_ms)
    except FileNotFoundError as e:
        duration_ms = int((perf_counter() - start) * 1000)
        msg = f"{description} skipped ({cmd[0]} not found)"
        if required:
            raise ForgeError(
                f"required tool '{cmd[0]}' not found on PATH (needed for: {description})"
            ) from e
        if not quiet:
            print(f"  [!!] {msg}")
        return Check(name=description, status="skip", details=msg, duration_ms=duration_ms)

    duration_ms = int((perf_counter() - start) * 1000)
    if result.returncode == 0:
        if not quiet:
            print(f"  [ok] {description}")
        return Check(name=description, status="ok", details="", duration_ms=duration_ms)

    if not quiet:
        print(f"  [!!] {description} failed")
    stderr_tail = ""
    if result.stderr:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        if not quiet:
            for line in stderr_tail.splitlines():
                print(f"       {line}")
    if required:
        suffix = f"\n{stderr_tail}" if stderr_tail else ""
        raise ForgeError(
            f"{description} failed (exit {result.returncode}): {' '.join(cmd)}{suffix}"
        )
    return Check(
        name=description,
        status="fail",
        details=stderr_tail or f"exit {result.returncode}",
        duration_ms=duration_ms,
    )

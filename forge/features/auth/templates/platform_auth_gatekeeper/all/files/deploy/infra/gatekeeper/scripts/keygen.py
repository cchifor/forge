#!/usr/bin/env python
# deploy/infra/gatekeeper/scripts/keygen.py
"""Idempotent ECDSA P-256 signing-key generator for the gatekeeper KeyRing.

Used as the ``gatekeeper-keygen`` one-shot service in docker-compose.yml.
Writes ``<dir>/active.pem`` if absent; never overwrites. Production
deployments should use ``KEY_BACKEND=kms`` instead of this script.

Run ad-hoc:

    uv run python deploy/infra/gatekeeper/scripts/keygen.py /path/to/secrets

Or via the container:

    docker compose run --rm gatekeeper-keygen
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _generate_active_pem(out_dir: Path) -> bool:
    """Generate ``active.pem`` if missing. Returns True if a key was written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "active.pem"
    if target.exists():
        print(f"keygen: {target} already exists; leaving it alone")
        return False

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    target.write_bytes(pem)
    # The keygen init container runs as root (to write into the named
    # volume) but the main gatekeeper reads the key as appuser (uid
    # 10001). Set 0644 so the unprivileged process can read the PEM.
    # The volume itself isn't host-mounted, so 0644 within the container
    # is acceptable for dev; production uses KEY_BACKEND=kms.
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    except (PermissionError, OSError):
        pass
    print(f"keygen: wrote {target} (ECDSA P-256, mode 0644)")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "out_dir",
        nargs="?",
        default=os.environ.get("SIGNING_KEY_DIR", "/run/secrets/gatekeeper-signing"),
        help="Directory to receive active.pem (default: $SIGNING_KEY_DIR)",
    )
    args = parser.parse_args(argv)
    _generate_active_pem(Path(args.out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# src/app/gatekeeper/key_store.py
"""KeyRing abstraction for ECDSA P-256 signing keys.

The KeyRing publishes public keys via the JWKS endpoint and signs
gatekeeper-minted internal JWTs. ECDSA over NIST P-256 (ES256) is chosen
over RSA: signing is roughly an order of magnitude cheaper at equivalent
security, signatures are smaller, and the algorithm has first-class AWS
KMS support (KeySpec=ECC_NIST_P256, KeyUsage=SIGN_VERIFY).

Three key states support a dual-key rotation window:

* ``active``   — signs new tokens; published in JWKS.
* ``retiring`` — does not sign; still published in JWKS so backends can
  verify tokens issued just before rotation. Dropped after the window.
* ``pending``  — published in JWKS but does not sign yet; pre-warms
  backend JWKS caches before promotion to ``active``.

The :class:`FileKeyRing` reads PEM files for dev. The :class:`KMSKeyRing`
is a deferred stub for prod (lands alongside IAM setup in a follow-up PR).
"""

from __future__ import annotations

import hashlib
import logging
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

import jwt as pyjwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)


class KeyState(StrEnum):
    ACTIVE = "active"
    RETIRING = "retiring"
    PENDING = "pending"


class KeyRingError(Exception):
    """Raised on key-material loading, parsing, or selection failures."""


@dataclass
class _KeyEntry:
    kid: str
    state: KeyState
    private_key: ec.EllipticCurvePrivateKey | None
    public_key: ec.EllipticCurvePublicKey


class KeyRing(Protocol):
    """Sign internal JWTs and publish their verification keys."""

    def sign(self, payload: dict[str, Any]) -> tuple[str, str]:
        """Encode *payload* as ES256 JWT signed by the active key.

        Returns ``(token, kid)``. The kid lets callers correlate signatures
        with their JWKS entries during rotation.
        """
        ...

    def public_jwks(self) -> dict[str, list[dict[str, str]]]:
        """Public JWK Set for ``/auth/jwks``. Excludes private material."""
        ...

    def reload(self) -> None:
        """Re-read key material from the underlying store."""
        ...


def _b64url(b: bytes) -> str:
    """Base64url without padding, per RFC 7515."""
    return urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _ec_public_to_jwk(
    public_key: ec.EllipticCurvePublicKey, kid: str
) -> dict[str, str]:
    """Serialize an EC P-256 public key as a JWK dict (RFC 7517)."""
    numbers = public_key.public_numbers()
    # P-256 coordinates are exactly 32 bytes each.
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
        "use": "sig",
        "alg": "ES256",
        "kid": kid,
    }


def kid_for_public_key(public_key: ec.EllipticCurvePublicKey) -> str:
    """Stable kid: SHA-256 of SubjectPublicKeyInfo, first 16 hex chars.

    Stability matters for rotation: the same key file always yields the
    same kid, so cached JWKS entries on backends remain valid across
    restarts and replicas.
    """
    spki = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()[:16]


@dataclass
class FileKeyRing:
    """File-backed KeyRing.

    Reads ``<key_dir>/active.pem`` (required), ``<key_dir>/retiring.pem``
    and ``<key_dir>/pending.pem`` (both optional). All files must contain
    PEM-encoded ECDSA P-256 private keys. The :func:`reload` method
    re-reads the directory, supporting hot rotation without restart.
    """

    key_dir: Path
    _entries: list[_KeyEntry] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        entries: list[_KeyEntry] = []
        for state in (KeyState.ACTIVE, KeyState.RETIRING, KeyState.PENDING):
            path = self.key_dir / f"{state.value}.pem"
            if not path.is_file():
                if state == KeyState.ACTIVE:
                    raise KeyRingError(
                        f"Active signing key missing at {path}. "
                        "Run scripts/keygen.py to generate one."
                    )
                continue

            pem = path.read_bytes()
            try:
                private_key = serialization.load_pem_private_key(pem, password=None)
            except Exception as exc:  # noqa: BLE001 — wrap any cryptography error
                raise KeyRingError(
                    f"Failed to load private key from {path}: {exc}"
                ) from exc

            if not isinstance(private_key, ec.EllipticCurvePrivateKey):
                raise KeyRingError(
                    f"{path} is not an ECDSA private key "
                    f"(got {type(private_key).__name__})"
                )
            if not isinstance(private_key.curve, ec.SECP256R1):
                raise KeyRingError(
                    f"{path} uses curve {private_key.curve.name}; "
                    "only secp256r1 (P-256) is accepted"
                )

            public_key = private_key.public_key()
            entries.append(
                _KeyEntry(
                    kid=kid_for_public_key(public_key),
                    state=state,
                    private_key=private_key,
                    public_key=public_key,
                )
            )

        self._entries = entries
        logger.info(
            "FileKeyRing loaded %d key(s) from %s: %s",
            len(entries),
            self.key_dir,
            [(e.state.value, e.kid) for e in entries],
        )

    def sign(self, payload: dict[str, Any]) -> tuple[str, str]:
        active = self._active_entry()
        assert active.private_key is not None  # invariant: active always has private
        token = pyjwt.encode(
            payload,
            active.private_key,
            algorithm="ES256",
            headers={"kid": active.kid},
        )
        return token, active.kid

    def public_jwks(self) -> dict[str, list[dict[str, str]]]:
        return {
            "keys": [
                _ec_public_to_jwk(entry.public_key, entry.kid)
                for entry in self._entries
            ]
        }

    def kids(self) -> list[tuple[str, KeyState]]:
        """Inspection helper: ``[(kid, state)]`` in load order."""
        return [(e.kid, e.state) for e in self._entries]

    def _active_entry(self) -> _KeyEntry:
        for entry in self._entries:
            if entry.state == KeyState.ACTIVE:
                return entry
        raise KeyRingError("No active key in ring")


class KMSKeyRing:
    """AWS KMS-backed KeyRing (deferred implementation).

    Production deployments will wrap an asymmetric KMS key
    (``KeySpec=ECC_NIST_P256``, ``KeyUsage=SIGN_VERIFY``):

    * ``sign`` calls ``kms:Sign`` with ``MessageType=DIGEST`` and the
      JWT's pre-computed SHA-256 digest.
    * ``public_jwks`` calls ``kms:GetPublicKey`` once at startup and
      caches; subsequent JWKS requests serve the cached JWK Set.
    * ``reload`` re-fetches the public key (used by a periodic refresh
      task to pick up KMS automatic rotation).

    This stub fails fast so misconfiguration surfaces at gatekeeper
    startup, not on the first request. Tracked under the gatekeeper
    KMS-KeyRing follow-up.
    """

    def __init__(self, key_arn: str) -> None:
        raise NotImplementedError(
            "KMSKeyRing is deferred. Phase 0 ships file-backed key storage "
            "only; the KMS backend lands alongside IAM setup."
        )


def load_key_ring(
    *,
    backend: str,
    key_dir: Path | None = None,
    kms_key_arn: str | None = None,
) -> KeyRing:
    """Construct the configured KeyRing implementation.

    Raises :class:`KeyRingError` for unknown backends or missing required
    parameters so configuration mistakes surface at startup.
    """
    if backend == "file":
        if key_dir is None:
            raise KeyRingError("file backend requires key_dir")
        return FileKeyRing(key_dir=key_dir)
    if backend == "kms":
        if kms_key_arn is None:
            raise KeyRingError("kms backend requires kms_key_arn")
        return cast(KeyRing, KMSKeyRing(key_arn=kms_key_arn))
    raise KeyRingError(f"Unknown key backend: {backend!r}")

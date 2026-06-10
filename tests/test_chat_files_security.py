"""Security regression tests for the chat-files template.

Two confirmed vulnerabilities the audit found (and a verifier reproduced):

  1. ``download_file`` accepted an absolute ``storage_path`` that pathlib's
     ``self.root / storage_path`` silently rebased to the filesystem root —
     ``GET /api/v1/chat-files//etc/passwd`` served arbitrary host files.
  2. Upload namespaced by a caller-supplied ``customer_id`` form field and
     downloads had no ownership check, so any tenant could read another's
     uploads.

The template modules import fastapi / generated-only ``forge_core`` packages
that are absent from forge's own test env, so — following the convention in
``test_gatekeeper_config_guards.py`` / ``test_generated_route_auth.py`` — the
contract is asserted on template source. The security-critical containment
MATH is additionally proven behaviorally with pure pathlib (the same
algorithm the template uses), so a logic bug can't hide behind a passing
source grep.
"""

from __future__ import annotations

from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_SERVICE = (
    _BASE
    / "forge/features/conversation/templates/file_upload/python/files/src/app/services/chat_file_service.py"
)
_ENDPOINT = (
    _BASE
    / "forge/features/conversation/templates/file_upload/python/files/src/app/api/v1/endpoints/chat_files.py"
)


def _contained(root: Path, storage_path: str) -> bool:
    """The exact containment predicate the hardened ``path_for`` uses:
    resolve both sides and require the result to be the root or under it."""
    root = root.resolve()
    full = (root / storage_path).resolve()
    return full == root or root in full.parents


class TestContainmentAlgorithm:
    """Behavioral proof of the resolve+parents math, independent of fastapi."""

    def test_absolute_path_escapes(self, tmp_path):
        root = tmp_path / "uploads"
        root.mkdir()
        # This is the original LFI — must be detected as NOT contained.
        assert not _contained(root, "/etc/passwd")

    def test_dotdot_escapes(self, tmp_path):
        root = tmp_path / "uploads"
        root.mkdir()
        assert not _contained(root, "../../../../etc/passwd")

    def test_relative_inside_root_is_contained(self, tmp_path):
        root = tmp_path / "uploads"
        root.mkdir()
        assert _contained(root, "tenant-a/abc__doc.pdf")

    def test_root_itself_is_contained(self, tmp_path):
        root = tmp_path / "uploads"
        root.mkdir()
        assert _contained(root, "")


class TestServiceTemplate:
    def _src(self) -> str:
        return _SERVICE.read_text(encoding="utf-8")

    def test_path_for_resolves_and_checks_containment(self):
        src = self._src()
        body = src.split("def path_for")[1].split("def delete")[0]
        assert ".resolve()" in body, "path_for must resolve before comparing"
        assert "parents" in body, "path_for must assert containment under root"
        # The vulnerable version was a bare ``return self.root / storage_path``.
        assert "return self.root / storage_path" not in src


class TestEndpointTenantScoping:
    def _src(self) -> str:
        return _ENDPOINT.read_text(encoding="utf-8")

    def test_does_not_trust_caller_supplied_customer_id(self):
        src = self._src()
        assert "Form(default=None)" not in src
        assert "customer_id: str | None = Form" not in src

    def test_derives_customer_id_from_verified_user(self):
        src = self._src()
        assert "_caller_customer_id" in src
        assert "user.customer_id" in src

    def test_download_is_tenant_scoped(self):
        src = self._src()
        assert "tenant_root" in src
        assert "in full.parents" in src

    def test_router_still_auth_gated(self):
        src = self._src()
        assert "from forge_core.security.auth import get_current_user" in src
        assert "dependencies=[Depends(get_current_user)]" in src

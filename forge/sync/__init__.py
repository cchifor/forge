"""Bidirectional-sync substrate — manifests, merge primitives, sentinels.

This package houses the modules that both forward (forge --update) and
reverse (forge --harvest) flows depend on. The forward direction lives
under ``forge/sync/forge_to_project/``; the reverse direction (added in
Phase 4) lives under ``forge/sync/project_to_forge/``.

Phase 3 of the bidirectional-sync plan moves the substrate modules here
from the top-level ``forge/`` package. The old import paths
(``from forge.merge``, ``from forge.provenance``, etc.) no longer
resolve — every internal caller has been updated to the new locations.
External callers (plugins, downstream tests) should import from this
package's public surface instead.
"""

from forge.sync.direction import UpdateMode, VerifyFailOn, VerifyScope
from forge.sync.lock import LOCK_DIRNAME, LOCK_FILENAME, acquire_lock
from forge.sync.manifest import (
    CURRENT_SCHEMA_VERSION,
    ForgeTomlData,
    read_forge_toml,
    write_forge_toml,
)
from forge.sync.merge import (
    FileMergeOutcome,
    ForwardDecision,
    MergeBlockCollector,
    MergeBlockRecord,
    MergeOutcome,
    ReverseDecision,
    SymmetricDecision,
    file_three_way_decide,
    is_binary_file,
    reverse_file_three_way_decide,
    reverse_three_way_decide,
    sha256_of_file,
    sha256_of_text,
    symmetric_file_three_way_decide,
    symmetric_three_way_decide,
    three_way_decide,
    write_file_sidecar,
    write_sidecar,
)
from forge.sync.provenance import (
    FileState,
    ProvenanceCollector,
    ProvenanceOrigin,
    ProvenanceRecord,
    classify,
    sha256_of,
)
from forge.sync.sentinel_audit import (
    SentinelIssue,
    SentinelIssueKind,
    audit_file,
    audit_targets,
    raise_if_corrupt,
)

__all__ = [
    # direction / scope types
    "UpdateMode",
    "VerifyFailOn",
    "VerifyScope",
    # lock
    "LOCK_DIRNAME",
    "LOCK_FILENAME",
    "acquire_lock",
    # manifest
    "CURRENT_SCHEMA_VERSION",
    "ForgeTomlData",
    "read_forge_toml",
    "write_forge_toml",
    # merge
    "FileMergeOutcome",
    "ForwardDecision",
    "MergeBlockCollector",
    "MergeBlockRecord",
    "MergeOutcome",
    "ReverseDecision",
    "SymmetricDecision",
    "file_three_way_decide",
    "is_binary_file",
    "reverse_file_three_way_decide",
    "reverse_three_way_decide",
    "sha256_of_file",
    "sha256_of_text",
    "symmetric_file_three_way_decide",
    "symmetric_three_way_decide",
    "three_way_decide",
    "write_file_sidecar",
    "write_sidecar",
    # provenance
    "FileState",
    "ProvenanceCollector",
    "ProvenanceOrigin",
    "ProvenanceRecord",
    "classify",
    "sha256_of",
    # sentinel_audit
    "SentinelIssue",
    "SentinelIssueKind",
    "audit_file",
    "audit_targets",
    "raise_if_corrupt",
]

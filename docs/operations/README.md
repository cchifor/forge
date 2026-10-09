# Operations

## Generated applications

- [Generated-code quality](generated-code-quality.md): ownership, architecture,
  updates, and unit/integration/E2E coverage gates.
- [Deployment](deployment.md): environment, secrets, ingress, data, and topology.
- [Troubleshooting](troubleshooting.md): installation and generation failures.

## Forge maintenance

- [Maintainer runbook](maintainer-runbook.md): releases, plugin isolation,
  provenance recovery, diagnostics, and coordinated dependency upgrades.
- [Validation matrix](validation-matrix.md): what generate, verify, smoke,
  round-trip, and update lanes measure.
- [Generator coverage policy](../coverage-policy.md): repository test ratchets.
- [Mutation testing](mutation-testing.md): critical-path behavioral checks.
- [Release procedures](../../RELEASING.md) and [upgrade notes](../../UPGRADING.md).

The generator's own coverage floor and a generated application's changed-line
coverage gate measure different code. Passing one does not satisfy the other.

[Documentation home](../README.md)

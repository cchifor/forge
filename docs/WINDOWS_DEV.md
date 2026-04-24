# Developing forge on Windows

CI tests forge on `windows-latest` in the Python matrix, so Windows is
a supported platform for both **using** forge and **developing** it.
This guide covers the Windows-specific friction points.

## Install

The `install` script at the repo root handles Windows via Git Bash or
WSL automatically — run `bash install` from a Git Bash terminal. Under
the hood it:

1. Installs `uv` via the Astral installer (PowerShell-based on
   Windows).
2. Refreshes the `PATH` so `uv` is visible in the current session.
3. Runs `uv tool install git+https://github.com/cchifor/forge.git`.

If PowerShell blocks the Astral script, open PowerShell as admin once
and run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`.

## Local dev setup

From Git Bash:

```bash
git clone https://github.com/cchifor/forge
cd forge
make install-dev
make check
```

Native Windows PowerShell works too, but some `make` targets rely on
POSIX shell features (`&&`, piping, heredocs) — Git Bash or WSL avoids
those papercuts.

## Line endings

- The repo uses LF endings everywhere (templates need LF so shebangs
  work in generated Linux containers).
- Git may warn `LF will be replaced by CRLF the next time Git touches
  it` on Windows — that's harmless (git's internal index still stores
  LF).
- If templates generated on Windows contain CRLF that breaks
  containerized tests, run `git config core.autocrlf input` in the
  clone and re-checkout.

## Known gotchas

- **Path length**: Windows' 260-char limit can bite when generation
  writes deeply nested `node_modules/`. Enable long paths via
  `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force`
  (requires admin + reboot).
- **Docker Compose**: Docker Desktop + WSL2 is strongly recommended
  over Docker Toolbox. Some fragments (observability_otel) rely on
  modern compose features Toolbox doesn't support.
- **E2E tests** (`make e2e`) require `uv`, `npm`, and `cargo` on PATH.
  Install via:
  - `winget install --id OpenJS.NodeJS.LTS` for Node.
  - `winget install --id Rustlang.Rustup` for Rust.
  - `uv` is already present after `make install-dev`.

## Troubleshooting

- `'bash' is not recognized`: install Git for Windows (comes with Git
  Bash). Or use WSL.
- `uv: command not found` after install: close and reopen your
  terminal so the refreshed PATH takes effect.
- `Permission denied` on `git commit`: the repo's pre-commit hooks
  need a POSIX shell — run from Git Bash, not Windows `cmd`.
- `forge --update` complains about merge conflicts: you have
  customised a file forge originally wrote. Resolve via the
  `.forge-merge` sidecar files, or see
  [`docs/troubleshooting.md`](troubleshooting.md).

"""Post-generation task: generate features, patch configs, build, test."""

import itertools
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Load answers from Copier
try:
    import yaml
except ImportError:
    # PyYAML may not be installed; fall back to simple parsing
    yaml = None


def load_answers():
    """Load variables from .copier-answers.yml."""
    answers_path = Path.cwd() / ".copier-answers.yml"
    if not answers_path.exists():
        print("  WARNING: .copier-answers.yml not found, using defaults")
        return {}
    if yaml:
        with open(answers_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    # Fallback: simple key: value parser
    answers = {}
    with open(answers_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line and not line.startswith("#") and not line.startswith("_"):
                key, _, val = line.partition(":")
                val = val.strip().strip("'\"")
                if val == "true":
                    val = True
                elif val == "false":
                    val = False
                elif val.isdigit():
                    val = int(val)
                answers[key.strip()] = val
    return answers


ANSWERS = load_answers()

PROJECT_NAME = ANSWERS.get("project_name", "My App")
PROJECT_SLUG = ANSWERS.get("project_slug", "my-app")
APP_TITLE = ANSWERS.get("app_title", PROJECT_NAME)
DESCRIPTION = ANSWERS.get("description", "A Svelte 5 SPA application")
VERSION = ANSWERS.get("version", "0.1.0")
FEATURES = ANSWERS.get("features", "items")
INCLUDE_AUTH = ANSWERS.get("include_auth", True)
INCLUDE_CHAT = ANSWERS.get("include_chat", True)
INCLUDE_OPENAPI = ANSWERS.get("include_openapi", True)
PACKAGE_MANAGER = ANSWERS.get("package_manager", "npm")
API_BASE_URL = ANSWERS.get("api_base_url", "http://localhost:5000")
API_PROXY_TARGET = ANSWERS.get("api_proxy_target", API_BASE_URL)
SERVER_PORT = str(ANSWERS.get("server_port", 5173))
KEYCLOAK_URL = ANSWERS.get("keycloak_url", "http://localhost:8080")
DEFAULT_COLOR_SCHEME = ANSWERS.get("default_color_scheme", "blue")

# WS2 multi-backend awareness — these come from forge.variable_mapper.svelte_context.
import json as _json  # noqa: E402

try:
    BACKEND_FEATURES = _json.loads(ANSWERS.get("backend_features") or "{}")
except (ValueError, TypeError):
    BACKEND_FEATURES = {}
try:
    PROXY_TARGETS = _json.loads(ANSWERS.get("proxy_targets") or "[]")
except (ValueError, TypeError):
    PROXY_TARGETS = []
VITE_PROXY_CONFIG = ANSWERS.get("vite_proxy_config", "") or ""

# Build entity → backend lookup so per-feature API files prefix correctly.
FEATURE_TO_BACKEND: dict = {}
for _bname, _binfo in BACKEND_FEATURES.items():
    for _f in (_binfo.get("features") or []):
        FEATURE_TO_BACKEND[_f] = _bname

DEFAULT_BACKEND = next(iter(BACKEND_FEATURES), "backend")

PROJECT_DIR = Path.cwd()

# Import feature templates
sys.path.insert(0, str(PROJECT_DIR / "_build"))
from feature_templates import (  # noqa: E402
    FEATURE_API,
    FEATURE_CARD,
    FEATURE_FILTERS,
    FEATURE_FORM,
    FEATURE_INDEX,
    FEATURE_SCHEMA,
    HUB_BOTTOM_NAV_ITEM,
    HUB_BREADCRUMB,
    HUB_DASHBOARD_CHIP,
    HUB_MSW_HANDLERS,
    HUB_SCHEMA_EXPORT,
    HUB_SIDEBAR_ITEM,
    HUB_TYPES,
    NO_CHAT_LAYOUT,
    ROUTE_CREATE,
    ROUTE_DETAIL,
    ROUTE_ERROR,
    ROUTE_LIST,
    make_feature_context,
)


# -- Progress spinner ---------------------------------------------------------

class Spinner:
    FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, message):
        self.message = message
        self._stop_event = threading.Event()
        self._thread = None
        self._start_time = 0.0

    def _spin(self):
        for frame in itertools.cycle(self.FRAMES):
            if self._stop_event.is_set():
                break
            elapsed = time.time() - self._start_time
            sys.stdout.write("\r  [%s] %s (%.0fs)" % (frame, self.message, elapsed))
            sys.stdout.flush()
            time.sleep(0.15)

    def start(self):
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self, success=True):
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        elapsed = time.time() - self._start_time
        icon = "ok" if success else "FAIL"
        sys.stdout.write("\r  [%s] %s (%.1fs)    \n" % (icon, self.message, elapsed))
        sys.stdout.flush()


# -- File I/O helpers ---------------------------------------------------------

def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_file(path):
    return path.read_text(encoding="utf-8")


def inject_marker(filepath, marker, content):
    text = filepath.read_text(encoding="utf-8")
    if marker not in text:
        return
    text = text.replace(marker, content + "\n" + marker)
    filepath.write_text(text, encoding="utf-8")


def remove_path(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()


def run_command(cmd, description, timeout=300):
    spinner = Spinner(description)
    spinner.start()
    try:
        result = subprocess.run(
            cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=timeout,
        )
        ok = result.returncode == 0
        spinner.stop(success=ok)
        if not ok and result.stderr:
            for line in result.stderr.strip().splitlines()[-10:]:
                print("    %s" % line)
        return ok
    except FileNotFoundError:
        spinner.stop(success=False)
        print("    Command not found: %s" % cmd[0])
        return False
    except subprocess.TimeoutExpired:
        spinner.stop(success=False)
        print("    Timed out after %ss" % timeout)
        return False


# -- Feature generation -------------------------------------------------------

def generate_features():
    features = [f.strip() for f in FEATURES.split(",") if f.strip()]

    for feature_name in features:
        ctx = make_feature_context(feature_name)
        print("  [+] %s" % feature_name)

        feat_base = PROJECT_DIR / "src" / "lib" / "features" / ctx["plural"]
        write_file(feat_base / "index.ts", FEATURE_INDEX.format(**ctx))
        write_file(feat_base / "api" / ("%s.ts" % ctx["plural"]), FEATURE_API.format(**ctx))
        write_file(feat_base / "model" / ("%s-filters.svelte.ts" % ctx["singular"]), FEATURE_FILTERS.format(**ctx))
        write_file(feat_base / "model" / ("%s-form.svelte.ts" % ctx["singular"]), FEATURE_FORM.format(**ctx))
        write_file(feat_base / "ui" / ("%sCard.svelte" % ctx["Singular"]), FEATURE_CARD.format(**ctx))

        write_file(
            PROJECT_DIR / "src" / "lib" / "core" / "schemas" / ("%s.schema.ts" % ctx["singular"]),
            FEATURE_SCHEMA.format(**ctx),
        )

        routes_base = PROJECT_DIR / "src" / "routes" / "(app)" / ctx["plural"]
        write_file(routes_base / "+page.svelte", ROUTE_LIST.format(**ctx))
        write_file(routes_base / "+error.svelte", ROUTE_ERROR.format(**ctx))
        write_file(routes_base / "new" / "+page.svelte", ROUTE_CREATE.format(**ctx))
        write_file(routes_base / "[id]" / "+page.svelte", ROUTE_DETAIL.format(**ctx))

        shell_ui = PROJECT_DIR / "src" / "lib" / "features" / "shell" / "ui"
        inject_marker(shell_ui / "AppSidebar.svelte", "// --- feature nav items ---", HUB_SIDEBAR_ITEM.format(**ctx))
        inject_marker(shell_ui / "BottomNav.svelte", "// --- feature nav items ---", HUB_BOTTOM_NAV_ITEM.format(**ctx))
        inject_marker(shell_ui / "AppHeader.svelte", "// --- feature route titles ---", HUB_BREADCRUMB.format(**ctx))
        inject_marker(PROJECT_DIR / "src" / "routes" / "(app)" / "+page.svelte", "<!-- --- feature action chips --- -->", HUB_DASHBOARD_CHIP.format(**ctx))
        inject_marker(PROJECT_DIR / "src" / "lib" / "core" / "schemas" / "index.ts", "// --- feature schema exports ---", HUB_SCHEMA_EXPORT.format(**ctx))
        inject_marker(PROJECT_DIR / "src" / "test" / "mocks" / "handlers.ts", "// --- feature mock handlers ---", HUB_MSW_HANDLERS.format(**ctx))
        inject_marker(PROJECT_DIR / "src" / "lib" / "core" / "api" / "generated" / "types.gen.ts", "// --- feature type definitions ---", HUB_TYPES.format(**ctx))

    return features


# -- Home API path patching ---------------------------------------------------

def patch_home_api_paths(first_backend: str) -> None:
    """Prefix health/info API paths with the first backend name for Traefik routing."""
    files_to_patch = [
        PROJECT_DIR / "src" / "lib" / "features" / "dashboard" / "api" / "health.ts",
        PROJECT_DIR / "src" / "lib" / "features" / "dashboard" / "api" / "info.ts",
        PROJECT_DIR / "src" / "test" / "mocks" / "handlers.ts",
    ]
    for fpath in files_to_patch:
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
            text = text.replace("api/v1/", f"api/{first_backend}/v1/")
            fpath.write_text(text, encoding="utf-8")


def patch_feature_api_paths() -> None:
    """Per-feature API path prefixing.

    For multi-backend deployments, each entity routes through its owning backend's
    Traefik prefix. The mapping comes from `backend_features` (built by
    forge.variable_mapper). Falls back to the default backend if no mapping exists.
    """
    if not FEATURE_TO_BACKEND:
        return
    features_dir = PROJECT_DIR / "src" / "lib" / "features"
    for feature_name, backend in FEATURE_TO_BACKEND.items():
        api_file = features_dir / feature_name / "api" / f"{feature_name}.ts"
        if not api_file.exists():
            continue
        text = api_file.read_text(encoding="utf-8")
        # The feature template emits `api/v1/{plural}` paths; patch them.
        new_text = text.replace("api/v1/", f"api/{backend}/v1/")
        if new_text != text:
            api_file.write_text(new_text, encoding="utf-8")
            print(f"  Patched {api_file.relative_to(PROJECT_DIR)} -> /api/{backend}/v1/")


# -- Config patching ----------------------------------------------------------

def patch_config_files():
    vite_config = PROJECT_DIR / "vite.config.ts"
    if not vite_config.exists():
        return
    content = read_file(vite_config)
    content = content.replace("port: 5173", "port: %s" % SERVER_PORT)
    if VITE_PROXY_CONFIG.strip():
        # Multi-backend project: replace the default single-target /api proxy with
        # the per-backend block built by forge.variable_mapper._build_vite_proxy_config.
        new_proxy = "proxy: {\n%s\n\t\t}" % VITE_PROXY_CONFIG
        content = content.replace(
            "proxy: {\n\t\t\t'/api': {\n"
            "\t\t\t\ttarget: 'http://localhost:5000',\n"
            "\t\t\t\tchangeOrigin: true\n"
            "\t\t\t}\n"
            "\t\t}",
            new_proxy,
        )
        # Fallback: if exact match didn't hit, just substitute the default target.
        content = content.replace("target: 'http://localhost:5000'", "target: '%s'" % API_PROXY_TARGET)
        print(
            "  Patched vite.config.ts (port=%s, multi-backend proxy with %d targets)"
            % (SERVER_PORT, len(PROXY_TARGETS))
        )
    else:
        content = content.replace(
            "target: 'http://localhost:5000'",
            "target: '%s'" % API_PROXY_TARGET,
        )
        print(
            "  Patched vite.config.ts (port=%s, proxy=%s)" % (SERVER_PORT, API_PROXY_TARGET)
        )
    vite_config.write_text(content, encoding="utf-8")


# -- README generation ---------------------------------------------------------

def generate_readme(features):
    feature_rows = ""
    feature_rows += "| **Home** | Dashboard with service info and health status | Built-in |\n"
    if INCLUDE_AUTH:
        feature_rows += "| **Auth** | OAuth2/Keycloak login with dev mode | Built-in |\n"
    feature_rows += "| **Profile** | User profile from JWT claims | Built-in |\n"
    feature_rows += "| **Settings** | Theme mode, color scheme, OLED dark mode | Built-in |\n"
    if INCLUDE_CHAT:
        feature_rows += "| **Chat** | AG-UI streaming chat + workspace + canvas | Built-in |\n"
    for f in features:
        ctx = make_feature_context(f)
        feature_rows += "| **%s** | CRUD operations for %s | Generated |\n" % (ctx["Plural"], ctx["plural"])

    pm = PACKAGE_MANAGER
    dev_cmd = "%s run dev" % pm

    feature_tree = ""
    for f in features:
        ctx = make_feature_context(f)
        feature_tree += "\n### %s (`features/%s/`)\n```\n%s/\n  index.ts\n  api/%s.ts\n  model/%s-filters.svelte.ts\n  model/%s-form.svelte.ts\n  ui/%sCard.svelte\n```\n" % (
            ctx["Plural"], ctx["plural"], ctx["plural"],
            ctx["plural"], ctx["singular"], ctx["singular"], ctx["Singular"])

    readme = """# %s

%s

## Quick Start

```bash
%s install
%s
```

## Features

| Feature | Description | Source |
|---------|-------------|--------|
%s
## Architecture

Feature-First with Svelte 5 runes, TanStack Query, Ky HTTP client, Zod validation.

### Responsive Layout
- **Expanded** (>1024px): Sidebar + working area + inline chat
- **Medium** (640-1024px): Collapsed sidebar + drawer chat
- **Compact** (<640px): Bottom navigation + modal chat
%s
""" + ("""
## Chat & agentic UI

When generated with `--include-chat`, the chat module under
`src/lib/features/chat/` provides a full AG-UI client:

- **Streaming responses** via `@ag-ui/client` HttpAgent (text-delta events).
- **Tool call status** (`ToolCallStatus.svelte`) shows running/completed/error.
- **HITL (Human-in-the-Loop)** prompts via `UserPromptCard.svelte`.
- **Workspace pane** (`WorkspacePane.svelte`) renders agent-opened activities:
  file explorer, credential form, approval review, user-prompt review.
- **Canvas pane** (`CanvasPane.svelte`) renders agent outputs: dynamic form,
  data table, report (markdown), code viewer, workflow diagram.
- **Model selector** + **approval mode** toggle in the chat header.

Mount `<WorkspacePane />` and `<CanvasPane />` next to your chat panel — they
render conditionally when the agent emits `activity_snapshot` events. Set the
agent endpoint via `VITE_AGENT_BASE_URL` (defaults to `${origin}/agent/`).

Add a custom workspace activity:

```ts
import { registerWorkspaceComponent } from '$lib/features/chat';
import MyActivity from './MyActivity.svelte';

registerWorkspaceComponent('my_activity_type', {
  component: MyActivity,
  label: 'My Activity'
});
```
""" if INCLUDE_CHAT else "") + """
## Running

```bash
%s
```

Dev server on port %s, proxying to `%s`.

## Project Info

- **Version**: %s
- **Package**: `%s`
""" % (
        PROJECT_NAME, DESCRIPTION,
        pm, dev_cmd,
        feature_rows,
        feature_tree,
        dev_cmd, SERVER_PORT, API_BASE_URL,
        VERSION, PROJECT_SLUG,
    )

    write_file(PROJECT_DIR / "README.md", readme.strip() + "\n")
    print("  Generated README.md")


# -- Optional file removal ----------------------------------------------------

def remove_optional_files():
    removed = []

    if not INCLUDE_AUTH:
        remove_path(PROJECT_DIR / "src" / "routes" / "login")
        remove_path(PROJECT_DIR / "src" / "lib" / "core" / "auth")
        remove_path(PROJECT_DIR / "static" / "silent-check-sso.html")
        removed.append("auth")

    if not INCLUDE_CHAT:
        remove_path(PROJECT_DIR / "src" / "lib" / "features" / "chat")
        remove_path(PROJECT_DIR / "src" / "lib" / "features" / "shell" / "ui" / "ChatDrawer.svelte")
        remove_path(PROJECT_DIR / "src" / "lib" / "features" / "shell" / "ui" / "ChatBottomSheet.svelte")
        remove_path(PROJECT_DIR / "src" / "lib" / "features" / "shell" / "ui" / "VerticalSplitHandle.svelte")

        layout_path = PROJECT_DIR / "src" / "routes" / "(app)" / "+layout.svelte"
        write_file(layout_path, NO_CHAT_LAYOUT)

        header_path = PROJECT_DIR / "src" / "lib" / "features" / "shell" / "ui" / "AppHeader.svelte"
        if header_path.exists():
            content = read_file(header_path)
            content = content.replace(", Sparkles", "")
            content = content.replace("\timport { Tooltip } from 'bits-ui';\n", "")
            start_marker = "\t\t<!-- AI Chat Button -->"
            end_marker = "\t\t</Tooltip.Root>\n"
            start_idx = content.find(start_marker)
            end_idx = content.find(end_marker, start_idx)
            if start_idx != -1 and end_idx != -1:
                content = content[:start_idx] + content[end_idx + len(end_marker):]
            header_path.write_text(content, encoding="utf-8")

        removed.append("chat")

    if removed:
        print("  Removed optional: %s" % ", ".join(removed))
    else:
        print("  All components enabled")


# -- Main ----------------------------------------------------------------------

def main():
    print()
    print("=" * 60)
    print("  Setting up: %s" % PROJECT_NAME)
    print("=" * 60)
    print()

    # 1. Generate features
    print("> Generating features")
    features = generate_features()
    print()

    # 1b. Patch home page API paths to use the backend route prefix
    patch_home_api_paths(DEFAULT_BACKEND)
    # 1c. Per-feature API prefixing for multi-backend projects
    patch_feature_api_paths()

    # 2. Configure
    print("> Configuring project")
    patch_config_files()
    generate_readme(features)
    remove_optional_files()
    print()

    # 3. Install dependencies
    print("> Building project")
    pm = shutil.which(PACKAGE_MANAGER)

    if not pm:
        print("  %s not found. Run manually:" % PACKAGE_MANAGER)
        print("    %s install" % PACKAGE_MANAGER)
        print()
        # Clean up _build even if install fails
        remove_path(PROJECT_DIR / "_build")
        return

    install_ok = run_command(
        [pm, "install"],
        "Installing dependencies (%s install)" % PACKAGE_MANAGER,
        timeout=300,
    )

    if not install_ok:
        print("\n  Install failed. Try: %s install\n" % PACKAGE_MANAGER)
        remove_path(PROJECT_DIR / "_build")
        return

    # 4. Validate
    print()
    print("> Validating project")
    run_command([pm, "run", "check"], "Running svelte-check", timeout=120)

    # 5. Build
    print()
    print("> Building for production")
    build_ok = run_command([pm, "run", "build"], "Building (vite build)", timeout=180)

    build_dir = PROJECT_DIR / "build"
    if build_ok and build_dir.is_dir():
        file_count = sum(1 for _ in build_dir.rglob("*") if _.is_file())
        print("  Build output: %s (%d files)" % (build_dir, file_count))

    # 6. Clean up _build
    remove_path(PROJECT_DIR / "_build")

    # 7. Git init
    git_bin = shutil.which("git")
    if git_bin:
        print()
        print("> Initializing repository")
        run_command([git_bin, "init"], "git init")
        run_command([git_bin, "add", "."], "git add .")
        run_command([git_bin, "commit", "-m", "Initial project from template"], "git commit")

    print()
    print("=" * 60)
    print("  Project ready: %s" % PROJECT_NAME)
    print("=" * 60)
    print()
    print("  Next steps:")
    print()
    print("    cd %s" % PROJECT_DIR.name)
    print("    %s run dev          # Start development server" % PACKAGE_MANAGER)
    print("    %s run preview      # Preview production build" % PACKAGE_MANAGER)
    print("    %s run check        # Run type checking" % PACKAGE_MANAGER)
    print("    %s run test:e2e     # Run E2E tests" % PACKAGE_MANAGER)
    print()


if __name__ == "__main__":
    main()

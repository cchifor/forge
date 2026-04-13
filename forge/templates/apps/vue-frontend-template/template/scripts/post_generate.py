"""Post-generation task: generates features, patches files, runs setup."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

# ─── Windows UTF-8 ───
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ─── Spinner ───

class Spinner:
    FRAMES = ["|", "/", "-", "\\"]

    def __init__(self, message: str) -> None:
        self.message = message
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    def __enter__(self) -> "Spinner":
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _spin(self) -> None:
        idx = 0
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._start_time
            frame = self.FRAMES[idx % len(self.FRAMES)]
            sys.stdout.write(f"\r  [{frame}] {self.message} ({elapsed:.0f}s)")
            sys.stdout.flush()
            idx += 1
            self._stop.wait(0.15)

    def finish(self, success: bool = True) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        elapsed = time.monotonic() - self._start_time
        icon = "ok" if success else "FAIL"
        sys.stdout.write(f"\r  [{icon}] {self.message} ({elapsed:.1f}s)    \n")
        sys.stdout.flush()


# ─── Load Configuration ───
# Copier renders _build/answers.json with template variables.
# The task runs with CWD = generated project directory.

import json

PROJECT_DIR = Path.cwd()
_answers_path = PROJECT_DIR / "scripts" / "answers.json"

if not _answers_path.exists():
    print(f"  [FAIL] answers.json not found at {_answers_path}")
    sys.exit(1)

_answers = json.loads(_answers_path.read_text(encoding="utf-8"))

FEATURES_RAW = _answers["features"]
BACKEND_FEATURES = _answers.get("backend_features", {})
PROXY_TARGETS = _answers.get("proxy_targets", [])
INCLUDE_AUTH = _answers["include_auth"]
INCLUDE_CHAT = _answers["include_chat"]
INCLUDE_OPENAPI = _answers["include_openapi"]
PACKAGE_MANAGER = _answers["package_manager"]
APP_TITLE = _answers["app_title"]
PROJECT_NAME = _answers["project_name"]
VERSION = _answers["version"]


# ─── Load feature_templates.py ───

_ft_path = PROJECT_DIR / "scripts" / "feature_templates.py"
if not _ft_path.exists():
    print(f"  [FAIL] feature_templates.py not found at {_ft_path}")
    sys.exit(1)

_spec = importlib.util.spec_from_file_location("feature_templates", _ft_path)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(_mod)  # type: ignore

make_feature_context = _mod.make_feature_context
INDEX_TEMPLATE = _mod.INDEX_TEMPLATE
API_COMPOSABLE_TEMPLATE = _mod.API_COMPOSABLE_TEMPLATE
SCHEMA_TEMPLATE = _mod.SCHEMA_TEMPLATE
SCHEMA_TEST_TEMPLATE = _mod.SCHEMA_TEST_TEMPLATE
LIST_PAGE_TEMPLATE = _mod.LIST_PAGE_TEMPLATE
CREATE_PAGE_TEMPLATE = _mod.CREATE_PAGE_TEMPLATE
DETAIL_PAGE_TEMPLATE = _mod.DETAIL_PAGE_TEMPLATE
MSW_HANDLERS_TEMPLATE = _mod.MSW_HANDLERS_TEMPLATE
HUB_ROUTER_IMPORT = _mod.HUB_ROUTER_IMPORT
HUB_ROUTER_ROUTE = _mod.HUB_ROUTER_ROUTE
HUB_SIDEBAR_NAV = _mod.HUB_SIDEBAR_NAV
HUB_MSW_IMPORT = _mod.HUB_MSW_IMPORT
HUB_MSW_SPREAD = _mod.HUB_MSW_SPREAD


# ─── File Helpers ───

def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def inject_after_marker(file_path: Path, marker: str, content: str) -> None:
    if not file_path.exists():
        return
    lines = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines: list[str] = []
    injected = False
    for line in lines:
        new_lines.append(line)
        if marker in line and not injected:
            new_lines.append(content)
            injected = True
    if injected:
        file_path.write_text("".join(new_lines), encoding="utf-8")


def delete_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def delete_file(path: Path) -> None:
    if path.exists():
        path.unlink()


# ─── Feature Generation ───

def generate_feature(ctx: dict[str, str]) -> None:
    base = PROJECT_DIR / "src" / "features" / ctx["plural"]
    write_file(base / "index.ts", INDEX_TEMPLATE.format(**ctx))
    write_file(base / "api" / f"use{ctx['Plural']}.ts", API_COMPOSABLE_TEMPLATE.format(**ctx))
    write_file(base / "model" / f"{ctx['singular']}.schema.ts", SCHEMA_TEMPLATE.format(**ctx))
    write_file(base / "model" / f"{ctx['singular']}.schema.test.ts", SCHEMA_TEST_TEMPLATE.format(**ctx))
    write_file(base / "ui" / f"{ctx['Plural']}ListPage.vue", LIST_PAGE_TEMPLATE.format(**ctx))
    write_file(base / "ui" / f"{ctx['Singular']}CreatePage.vue", CREATE_PAGE_TEMPLATE.format(**ctx))
    write_file(base / "ui" / f"{ctx['Singular']}DetailPage.vue", DETAIL_PAGE_TEMPLATE.format(**ctx))


def generate_msw_handlers(ctx: dict[str, str]) -> None:
    handlers_dir = PROJECT_DIR / "src" / "shared" / "mocks"
    write_file(handlers_dir / f"{ctx['plural']}.handlers.ts", MSW_HANDLERS_TEMPLATE.format(**ctx))


def inject_feature_into_hubs(ctx: dict[str, str]) -> None:
    router_file = PROJECT_DIR / "src" / "app" / "router" / "index.ts"
    sidebar_file = PROJECT_DIR / "src" / "shared" / "components" / "AppSidebar.vue"
    handlers_file = PROJECT_DIR / "src" / "shared" / "mocks" / "handlers.ts"

    inject_after_marker(router_file, "// --- feature imports ---", HUB_ROUTER_IMPORT.format(**ctx))
    inject_after_marker(router_file, "// --- feature routes ---", HUB_ROUTER_ROUTE.format(**ctx))
    inject_after_marker(sidebar_file, "// --- feature nav items ---", HUB_SIDEBAR_NAV.format(**ctx))
    inject_after_marker(handlers_file, "// --- feature handler imports ---", HUB_MSW_IMPORT.format(**ctx))
    inject_after_marker(handlers_file, "// --- feature handlers ---", HUB_MSW_SPREAD.format(**ctx))


# ─── Conditional Patching ───

APP_VUE_NO_CHAT = """\
<script setup lang="ts">
import { Toaster } from 'vue-sonner'
</script>

<template>
  <RouterView />
  <Toaster
    position="bottom-right"
    :expand="true"
    rich-colors
    close-button
  />
</template>
"""

MAIN_LAYOUT_NO_CHAT = """\
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Home, Package, User, Settings } from 'lucide-vue-next'
import AppSidebar from '@/shared/components/AppSidebar.vue'
import AppHeader from '@/shared/components/AppHeader.vue'
import { useBreakpoint } from '@/shared/composables/useBreakpoint'

const route = useRoute()
const { isCompact, isMedium, isExpanded } = useBreakpoint()

const bottomNavItems = [
  { title: 'Home', url: '/', icon: Home },
  { title: 'Items', url: '/items', icon: Package },
  { title: 'Profile', url: '/profile', icon: User },
  { title: 'Settings', url: '/settings', icon: Settings },
]

function isNavActive(url: string) {
  if (url === '/') return route.path === '/'
  return route.path.startsWith(url)
}
</script>

<template>
  <div v-if="isExpanded" class="flex h-svh overflow-hidden">
    <AppSidebar />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppHeader />
      <main class="flex-1 overflow-auto p-4"><RouterView /></main>
    </div>
  </div>
  <div v-else-if="isMedium" class="flex h-svh overflow-hidden">
    <AppSidebar :force-collapsed="true" />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppHeader />
      <main class="flex-1 overflow-auto p-4"><RouterView /></main>
    </div>
  </div>
  <div v-else class="flex h-svh flex-col overflow-hidden">
    <AppHeader :compact="true" />
    <main class="flex-1 overflow-auto p-4"><RouterView /></main>
    <nav class="flex h-14 shrink-0 items-center border-t bg-card">
      <RouterLink
        v-for="item in bottomNavItems" :key="item.url" :to="item.url"
        class="flex flex-1 flex-col items-center gap-0.5 py-2 text-xs interactive-press"
        :class="isNavActive(item.url) ? 'text-primary' : 'text-muted-foreground'"
      >
        <component :is="item.icon" class="h-5 w-5" />
        <span>{{ item.title }}</span>
      </RouterLink>
    </nav>
  </div>
</template>
"""

USE_AUTH_NO_KEYCLOAK = """\
import { ref, computed, readonly } from 'vue'

export interface AuthUser {
  id: string; email: string; username: string; firstName: string
  lastName: string; roles: string[]; customerId: string; orgId: string | null
}

const user = ref<AuthUser | null>(null)
const isLoading = ref(false)
const isInitialized = ref(false)

const DEV_USER: AuthUser = {
  id: '00000000-0000-0000-0000-000000000001', email: 'dev@localhost',
  username: 'dev-user', firstName: 'Dev', lastName: 'User',
  roles: ['admin', 'user'], customerId: '00000000-0000-0000-0000-000000000001', orgId: null,
}

export function useAuth() {
  const isAuthenticated = computed(() => !!user.value)
  async function init() { if (!isInitialized.value) { user.value = DEV_USER; isLoading.value = false; isInitialized.value = true } }
  async function getToken(): Promise<string | null> { return 'dev-token' }
  function login() { user.value = DEV_USER }
  function logout() { user.value = null }
  function hasRole(role: string): boolean { return user.value?.roles.includes(role) ?? false }
  return { user: readonly(user), isAuthenticated, isLoading: readonly(isLoading), init, getToken, login, logout, hasRole }
}
"""


def patch_home_api_paths(first_backend: str) -> None:
    """Prefix health/info API paths with the first backend name for Traefik routing."""
    files_to_patch = [
        PROJECT_DIR / "src" / "features" / "home" / "api" / "useHealth.ts",
        PROJECT_DIR / "src" / "features" / "home" / "api" / "useInfo.ts",
        PROJECT_DIR / "src" / "shared" / "mocks" / "handlers.ts",
        PROJECT_DIR / "src" / "shared" / "mocks" / "handlers.test.ts",
        PROJECT_DIR / "src" / "features" / "home" / "api" / "useHealth.test.ts",
    ]
    for fpath in files_to_patch:
        if fpath.exists():
            text = fpath.read_text(encoding="utf-8")
            text = text.replace("api/v1/", f"api/{first_backend}/v1/")
            fpath.write_text(text, encoding="utf-8")


def patch_conditional_files() -> None:
    # Patch sidebar branding (can't use Jinja2 in .vue files due to {{ }} conflicts)
    sidebar = PROJECT_DIR / "src" / "shared" / "components" / "AppSidebar.vue"
    if sidebar.exists():
        content = sidebar.read_text(encoding="utf-8")
        content = content.replace("{{ app_title }}", APP_TITLE)
        sidebar.write_text(content, encoding="utf-8")

    if not INCLUDE_CHAT:
        app_vue = PROJECT_DIR / "src" / "app" / "App.vue"
        app_vue.write_text(APP_VUE_NO_CHAT, encoding="utf-8")

        header = PROJECT_DIR / "src" / "shared" / "components" / "AppHeader.vue"
        if header.exists():
            content = header.read_text(encoding="utf-8")
            lines = [l for l in content.splitlines(keepends=True) if "AiChatButton" not in l and "ai_chat" not in l]
            header.write_text("".join(lines), encoding="utf-8")

        layout = PROJECT_DIR / "src" / "shared" / "layouts" / "MainLayout.vue"
        if layout.exists():
            layout.write_text(MAIN_LAYOUT_NO_CHAT, encoding="utf-8")

    if not INCLUDE_AUTH:
        auth_file = PROJECT_DIR / "src" / "shared" / "composables" / "useAuth.ts"
        auth_file.write_text(USE_AUTH_NO_KEYCLOAK, encoding="utf-8")


def remove_conditional_files() -> list[str]:
    removed: list[str] = []
    if not INCLUDE_AUTH:
        delete_dir(PROJECT_DIR / "src" / "features" / "auth")
        removed.append("auth")
    if not INCLUDE_CHAT:
        delete_dir(PROJECT_DIR / "src" / "features" / "ai_chat")
        removed.append("ai_chat")
    if not INCLUDE_OPENAPI:
        delete_file(PROJECT_DIR / "openapi-snapshot.json")
        delete_file(PROJECT_DIR / "openapi-ts.config.ts")
        removed.append("openapi")
    return removed


# ─── README ───

def patch_readme(feature_names: list[str]) -> None:
    pm = PACKAGE_MANAGER
    features_table = "| Feature | Route | Description |\n|---|---|---|\n"
    features_table += "| Home | `/` | Dashboard with service health and quick actions |\n"
    for name in feature_names:
        ctx = make_feature_context(name)
        features_table += f"| {ctx['Plural']} | `/{ctx['plural']}` | CRUD management for {ctx['plural']} |\n"
    features_table += "| Profile | `/profile` | User profile from JWT token |\n"
    features_table += "| Settings | `/settings` | Theme, color scheme, dark mode preferences |\n"
    if INCLUDE_AUTH:
        features_table += "| Auth | `/login` | Keycloak OAuth2 login |\n"
    if INCLUDE_CHAT:
        features_table += "| AI Chat | Ctrl+J | AI assistant panel |\n"

    scripts_table = "| Script | Description |\n|---|---|\n"
    scripts_table += f"| `{pm} run dev` | Start dev server |\n"
    scripts_table += f"| `{pm} run build` | Type-check + production build |\n"
    scripts_table += f"| `{pm} run test` | Run tests with Vitest |\n"
    scripts_table += f"| `{pm} run lint` | Lint with ESLint |\n"
    scripts_table += f"| `{pm} run type-check` | TypeScript type checking |\n"
    if INCLUDE_OPENAPI:
        scripts_table += f"| `{pm} run codegen` | Regenerate API types from OpenAPI spec |\n"

    tech = "- **Framework**: Vue 3 + TypeScript + Vite\n"
    tech += "- **UI**: Shadcn-Vue (Radix Vue + Tailwind CSS 4)\n"
    tech += "- **State**: Pinia (client) + TanStack Vue Query (server)\n"
    tech += "- **HTTP**: Ky + Zod runtime validation\n"
    if INCLUDE_AUTH:
        tech += "- **Auth**: Keycloak (OAuth2 + PKCE)\n"
    tech += "- **Testing**: Vitest + MSW\n"
    tech += "- **Icons**: Lucide Vue Next\n"

    content = f"# {APP_TITLE}\n\n{PROJECT_NAME} - a Vue 3 SPA.\n\n"
    content += f"## Tech Stack\n\n{tech}\n"
    content += f"## Features\n\n{features_table}\n"
    content += f"## Scripts\n\n{scripts_table}\n"
    content += f"## Getting Started\n\n```bash\ncd {PROJECT_DIR.name}\n{pm} install\n{pm} run dev\n```\n"

    (PROJECT_DIR / "README.md").write_text(content, encoding="utf-8")


# ─── Subprocess Runner ───

def run_command(label: str, cmd: list[str], timeout: int = 300) -> bool:
    spinner = Spinner(label)
    try:
        with spinner:
            result = subprocess.run(cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True, timeout=timeout)
        success = result.returncode == 0
        spinner.finish(success)
        if not success and result.stderr:
            for line in result.stderr.strip().splitlines()[-10:]:
                print(f"    {line}")
        return success
    except FileNotFoundError:
        spinner.finish(False)
        print(f"    {cmd[0]} not found in PATH")
        return False
    except subprocess.TimeoutExpired:
        spinner.finish(False)
        print(f"    Timed out after {timeout}s")
        return False


# ─── Main ───

def main() -> None:
    print("=" * 60)
    print(f"  Setting up: {PROJECT_NAME}")
    print("=" * 60)

    # Build feature list with backend_name mapping
    feature_backend_map: dict[str, str] = {}
    if BACKEND_FEATURES:
        for backend_name, info in BACKEND_FEATURES.items():
            for feat in info.get("features", []):
                feature_backend_map[feat.strip()] = backend_name

    # Fallback: parse from flat features string if no backend mapping
    features = [f.strip() for f in FEATURES_RAW.split(",") if f.strip()]
    if not feature_backend_map:
        default_backend = "backend"
        for feat in features:
            feature_backend_map[feat] = default_backend

    print("\n> Generating features")
    for name in features:
        ctx = make_feature_context(name)
        ctx["backend_name"] = feature_backend_map.get(name, "backend")
        generate_feature(ctx)
        generate_msw_handlers(ctx)
        inject_feature_into_hubs(ctx)
        print(f"    {ctx['plural']}: 8 files → /api/{ctx['backend_name']}/v1/{ctx['plural']}")
    print(f"  Generated {len(features)} feature(s): {', '.join(features)}")

    # Patch home page API paths to use the first backend's route prefix
    first_backend = next(iter(feature_backend_map.values()), "backend")
    patch_home_api_paths(first_backend)

    print("\n> Patching conditional files")
    patch_conditional_files()
    print(f"  [ok] Conditionals applied")

    print("\n> Configuring optional components")
    removed = remove_conditional_files()
    if removed:
        print("  Removed: " + ", ".join(removed))
    else:
        print("  All components enabled")

    print("\n> Updating README")
    patch_readme(features)
    print("  [ok] README.md updated")

    pm = PACKAGE_MANAGER
    print(f"\n> Installing project")
    run_command(f"Installing dependencies ({pm} install)", [pm, "install"])
    run_command("Type checking (vue-tsc)", [pm, "run", "type-check"])
    run_command("Linting (eslint)", [pm, "run", "lint"])

    # Clean up build scripts (must happen after all Python work is done)
    # We can't delete ourselves while running, so just remove answers.json
    # and feature_templates.py. The scripts/ dir is cleaned by .gitignore or manually.
    delete_file(PROJECT_DIR / "scripts" / "answers.json")
    delete_file(PROJECT_DIR / "scripts" / "feature_templates.py")

    print("\n> Initializing repository")
    if shutil.which("git"):
        run_command("git init", ["git", "init"])
        run_command("git add", ["git", "add", "."])
        run_command("git commit", ["git", "commit", "-m", "Initial commit from vue-frontend-copier"])
    else:
        print("  git not found, skipping")

    print("\n" + "=" * 60)
    print(f"  Project ready: {PROJECT_NAME}")
    print("=" * 60)
    print(f"\n  cd {PROJECT_DIR.name}")
    print(f"  {pm} run dev          Start the dev server")
    print(f"  {pm} run test         Run tests")
    print(f"  {pm} run build        Production build\n")


if __name__ == "__main__":
    main()

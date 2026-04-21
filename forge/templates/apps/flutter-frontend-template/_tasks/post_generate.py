"""Post-generation task: scaffold platform, generate features, build, test."""

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

# Copier runs tasks with cwd set to the destination directory.
# The actual project is inside {{project_slug}}/ subdirectory.
# We'll set PROJECT_DIR after parsing args.

# Parse command-line arguments (passed by Copier via copier.yml _tasks)
import argparse

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-slug", default="my_app")
    parser.add_argument("--project-name", default="My App")
    parser.add_argument("--app-title", default="")
    parser.add_argument("--org-name", default="com.example")
    parser.add_argument("--features", default="items")
    parser.add_argument("--include-auth", default="True")
    parser.add_argument("--include-chat", default="True")
    parser.add_argument("--include-openapi", default="True")
    parser.add_argument("--description", default="A Flutter application")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--api-base-url", default="http://localhost:5000/api/v1")
    parser.add_argument("--default-color-scheme", default="blue")
    # backend_features is a JSON object — passing it as a CLI arg breaks on
    # Windows cmd.exe because single quotes aren't honored. Copier renders
    # ``.forge_answers.json`` into the project directory instead; we read it
    # below after parsing args.
    return parser.parse_args()

import json as _json  # noqa: E402

_args = parse_args()
PROJECT_SLUG = _args.project_slug
PROJECT_DIR = Path.cwd() / PROJECT_SLUG
PACKAGE_NAME = _args.project_slug
PROJECT_NAME = _args.project_name
APP_TITLE = _args.app_title or PROJECT_NAME
ORG_NAME = _args.org_name
FEATURES = _args.features
INCLUDE_AUTH = _args.include_auth.lower() == "true"
INCLUDE_CHAT = _args.include_chat.lower() == "true"
INCLUDE_OPENAPI = _args.include_openapi.lower() == "true"
DESCRIPTION = _args.description
VERSION = _args.version
API_BASE_URL = _args.api_base_url
DEFAULT_COLOR_SCHEME = _args.default_color_scheme

# WS2: per-feature backend routing for multi-backend deployments.
# Read from the rendered .forge_answers.json sibling file instead of a CLI arg
# — cmd.exe on Windows doesn't grouping-quote JSON strings, which made the old
# --backend-features arg explode on `{` tokens.
_answers_file = PROJECT_DIR / ".forge_answers.json"
try:
    _answers = _json.loads(_answers_file.read_text(encoding="utf-8")) if _answers_file.exists() else {}
    BACKEND_FEATURES = _answers.get("backend_features", {}) or {}
except (ValueError, TypeError, OSError):
    BACKEND_FEATURES = {}
# Clean up the answers file — it's transport, not a runtime artifact.
try:
    if _answers_file.exists():
        _answers_file.unlink()
except OSError:
    pass
FEATURE_TO_BACKEND: dict = {}
for _bname, _binfo in BACKEND_FEATURES.items():
    for _f in (_binfo.get("features") or []):
        FEATURE_TO_BACKEND[_f] = _bname
DEFAULT_BACKEND = next(iter(BACKEND_FEATURES), "backend")
IS_MULTI_BACKEND = len(BACKEND_FEATURES) > 1

# Load feature templates from _tasks directory (alongside this script)
TASKS_DIR = Path(__file__).parent
sys.path.insert(0, str(TASKS_DIR))
from feature_templates import (  # noqa: E402
    CARD_WIDGET_TEMPLATE,
    CONTROLLER_TEMPLATE,
    CREATE_PAGE_TEMPLATE,
    DETAIL_PAGE_TEMPLATE,
    FIXTURE_TEMPLATE,
    FORM_WIDGET_TEMPLATE,
    HUB_BREADCRUMB,
    HUB_NAV_DESTINATION,
    HUB_ROUTE_NAMES,
    HUB_ROUTER_BRANCH,
    HUB_ROUTER_IMPORT,
    IMPORT_LINT_RULE,
    LIST_PAGE_TEMPLATE,
    QUERY_PARAMS_TEMPLATE,
    REPO_TEST_TEMPLATE,
    REPOSITORY_TEMPLATE,
    ROUTES_TEMPLATE,
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


# -- Helpers ------------------------------------------------------------------

def write_file(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

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
    # Windows: subprocess.run doesn't walk PATHEXT for bare tool names.
    resolved = shutil.which(cmd[0])
    if resolved is not None:
        cmd = [resolved, *cmd[1:]]
    try:
        result = subprocess.run(
            cmd, cwd=str(PROJECT_DIR), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
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


# -- Flutter scaffold ---------------------------------------------------------

def scaffold_flutter_project():
    import tempfile
    flutter_bin = shutil.which("flutter")
    if not flutter_bin:
        print("  Skipped (flutter not found)")
        return

    spinner = Spinner("Running flutter create")
    spinner.start()
    tmp = Path(tempfile.mkdtemp(prefix="flutter_tpl_"))
    try:
        result = subprocess.run(
            [flutter_bin, "create", "--org", ORG_NAME, "--project-name", PROJECT_SLUG,
             "--platforms", "web,android,ios,windows,macos,linux", "--no-pub", PROJECT_SLUG],
            cwd=str(tmp), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        if result.returncode != 0:
            spinner.stop(success=False)
            return

        scaffold_dir = tmp / PROJECT_SLUG
        for d in ["android", "ios", "linux", "macos", "windows", "web"]:
            src = scaffold_dir / d
            dst = PROJECT_DIR / d
            if src.is_dir() and not dst.exists():
                shutil.copytree(str(src), str(dst))
            elif src.is_dir() and dst.exists():
                for item in src.iterdir():
                    target = dst / item.name
                    if not target.exists():
                        if item.is_dir():
                            shutil.copytree(str(item), str(target))
                        else:
                            shutil.copy2(str(item), str(target))

        for f in [".gitignore", ".metadata"]:
            s = scaffold_dir / f
            d = PROJECT_DIR / f
            if s.exists() and not d.exists():
                shutil.copy2(str(s), str(d))

        spinner.stop(success=True)
    except Exception:
        spinner.stop(success=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# -- Feature generation -------------------------------------------------------

def generate_features():
    features = [f.strip() for f in FEATURES.split(",") if f.strip()]
    for feature_name in features:
        ctx = make_feature_context(feature_name, PACKAGE_NAME)
        print("  [+] %s" % feature_name)

        base = PROJECT_DIR / "lib" / "src" / "features" / ctx["plural"]
        templates = {}
        templates[base / ("%s_routes.dart" % ctx["plural"])] = ROUTES_TEMPLATE
        templates[base / "data" / ("%s_repository.dart" % ctx["plural"])] = REPOSITORY_TEMPLATE
        templates[base / "domain" / ("%s_query_params.dart" % ctx["plural"])] = QUERY_PARAMS_TEMPLATE
        templates[base / "presentation" / ("%s_controller.dart" % ctx["plural"])] = CONTROLLER_TEMPLATE
        templates[base / "presentation" / ("%s_list_page.dart" % ctx["plural"])] = LIST_PAGE_TEMPLATE
        templates[base / "presentation" / ("%s_detail_page.dart" % ctx["singular"])] = DETAIL_PAGE_TEMPLATE
        templates[base / "presentation" / ("%s_create_page.dart" % ctx["singular"])] = CREATE_PAGE_TEMPLATE
        templates[base / "presentation" / "widgets" / ("%s_card.dart" % ctx["singular"])] = CARD_WIDGET_TEMPLATE
        templates[base / "presentation" / "widgets" / ("%s_form.dart" % ctx["singular"])] = FORM_WIDGET_TEMPLATE

        for path, template in templates.items():
            write_file(path, template.format(**ctx))

        test_base = PROJECT_DIR / "test"
        write_file(test_base / "fixtures" / ("%s.dart" % ctx["plural"]), FIXTURE_TEMPLATE.format(**ctx))
        write_file(
            test_base / "src" / "features" / ctx["plural"] / ("%s_repository_test.dart" % ctx["plural"]),
            REPO_TEST_TEMPLATE.format(**ctx),
        )

        routing = PROJECT_DIR / "lib" / "src" / "routing"
        layout = PROJECT_DIR / "lib" / "src" / "shared" / "layout"
        inject_marker(routing / "route_names.dart", "// --- feature route names ---", HUB_ROUTE_NAMES.format(**ctx))
        inject_marker(routing / "app_router.dart", "// --- feature imports ---", HUB_ROUTER_IMPORT.format(**ctx))
        inject_marker(routing / "app_router.dart", "// --- feature branches ---", HUB_ROUTER_BRANCH.format(**ctx))
        inject_marker(layout / "nav_destinations.dart", "// --- feature nav destinations ---", HUB_NAV_DESTINATION.format(**ctx))
        inject_marker(layout / "breadcrumb_bar.dart", "// --- feature breadcrumb names ---", HUB_BREADCRUMB.format(**ctx))

    return features


def generate_import_lint(features):
    all_features = ["home", "profile", "settings"]
    if INCLUDE_AUTH:
        all_features.append("auth")
    if INCLUDE_CHAT:
        all_features.append("chat")
    all_features.extend(features)

    rules = []
    for feature in all_features:
        others = [f for f in all_features if f != feature]
        not_allow = "\n".join('      - ".*/features/%s/.*"' % o for o in others)
        rules.append(IMPORT_LINT_RULE.format(plural=feature, not_allow_lines=not_allow))

    write_file(PROJECT_DIR / "import_analysis_options.yaml", "rules:\n" + "\n\n".join(rules) + "\n")
    print("  Generated import lint rules (%d features)" % len(all_features))


# -- Web + README + cleanup ---------------------------------------------------

def patch_web_files():
    index_html = PROJECT_DIR / "web" / "index.html"
    if index_html.exists():
        content = index_html.read_text(encoding="utf-8")
        content = content.replace("<title>%s</title>" % PROJECT_SLUG, "<title>%s</title>" % PROJECT_NAME)
        content = content.replace("<title>my_app</title>", "<title>%s</title>" % PROJECT_NAME)
        index_html.write_text(content, encoding="utf-8")

    # silent-check-sso.html removed — Gatekeeper handles auth on web


def generate_readme(features):
    feature_rows = "| **Home** | Dashboard with service info and health status | Built-in |\n"
    if INCLUDE_AUTH:
        feature_rows += "| **Auth** | OAuth2/Keycloak login with dev mode | Built-in |\n"
    feature_rows += "| **Profile** | User profile from JWT claims | Built-in |\n"
    feature_rows += "| **Settings** | Theme mode, color scheme, OLED dark mode | Built-in |\n"
    if INCLUDE_CHAT:
        feature_rows += "| **Chat** | AG-UI streaming chat + workspace + canvas | Built-in |\n"
    for f in features:
        ctx = make_feature_context(f, PACKAGE_NAME)
        feature_rows += "| **%s** | CRUD operations for %s | Generated |\n" % (ctx["Plural"], ctx["plural"])

    feature_tree = ""
    for f in features:
        ctx = make_feature_context(f, PACKAGE_NAME)
        feature_tree += "\n### %s (`features/%s/`)\n```\n%s/\n  %s_routes.dart\n  data/%s_repository.dart\n  domain/%s_query_params.dart\n  presentation/\n    %s_controller.dart\n    %s_list_page.dart\n    %s_detail_page.dart\n    %s_create_page.dart\n    widgets/\n      %s_card.dart\n      %s_form.dart\n```\n" % (
            ctx["Plural"], ctx["plural"], ctx["plural"], ctx["plural"], ctx["plural"], ctx["plural"],
            ctx["plural"], ctx["plural"], ctx["singular"], ctx["singular"], ctx["singular"], ctx["singular"])

    chat_section = ""
    if INCLUDE_CHAT:
        chat_section = (
            "\n## Chat & agentic UI\n\n"
            "When generated with `--include-chat`, `lib/src/features/chat/` ships a\n"
            "Dart-native AG-UI client (Dio SSE + JSON-Patch reducer + Riverpod state):\n\n"
            "- **Streaming responses** via `AgUiClient` consuming `text/event-stream`.\n"
            "- **Tool call status** chips (`ToolCallStatusChip`).\n"
            "- **HITL prompts** rendered inline via `UserPromptCard`.\n"
            "- **Workspace pane** (`WorkspacePane`) for file explorer, credential\n"
            "  forms, approval reviews, user-prompt reviews.\n"
            "- **Canvas pane** (`CanvasPane`) for dynamic forms, data tables,\n"
            "  reports, code viewers, workflow diagrams.\n\n"
            "Configure the agent endpoint via `--dart-define=AGENT_BASE_URL=...`\n"
            "(defaults to `/agent/`). Add a custom workspace activity:\n\n"
            "```dart\n"
            "WorkspaceRegistry.register('my_activity', WorkspaceRegistryEntry(\n"
            "  label: 'My Activity',\n"
            "  builder: (ctx, activity, onAction) => MyActivity(activity: activity),\n"
            "));\n"
            "```\n"
        )
    readme = "# %s\n\n%s\n\n## Quick Start\n\n```bash\ncd %s\nflutter run --dart-define=AUTH_DISABLED=true --dart-define=API_BASE_URL=%s\n```\n\n## Features\n\n| Feature | Description | Source |\n|---------|-------------|--------|\n%s\n## Feature Modules\n%s%s\n## Testing\n\n```bash\nflutter test\n```\n\n## Project Info\n\n- **Version**: %s\n- **Package**: `%s`\n" % (
        PROJECT_NAME, DESCRIPTION, PROJECT_SLUG, API_BASE_URL,
        feature_rows, feature_tree, chat_section, VERSION, PACKAGE_NAME)

    write_file(PROJECT_DIR / "README.md", readme)
    print("  Generated README.md")


_NO_AUTH_APP_ROUTER = """\
import 'package:go_router/go_router.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../features/home/home_routes.dart';
// --- feature imports ---
import '../features/settings/settings_routes.dart';
import 'navigator_keys.dart';
import 'scaffold_with_nav.dart';

part 'app_router.g.dart';

@Riverpod(keepAlive: true)
GoRouter goRouter(Ref ref) {
  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/',
    routes: [
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return ScaffoldWithNav(navigationShell: navigationShell);
        },
        branches: [
          StatefulShellBranch(routes: HomeRoutes.routes),
          // --- feature branches ---
          StatefulShellBranch(routes: SettingsRoutes.routes),
        ],
      ),
    ],
  );
}
"""


_NO_AUTH_INTERCEPTOR = """\
import 'package:dio/dio.dart';

/// No-op interceptor — this build was generated with include_auth=false.
/// Backends running without auth shouldn't require a Bearer token.
class AuthInterceptor extends Interceptor {
  AuthInterceptor(Object _);

  @override
  void onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) {
    handler.next(options);
  }
}
"""


def _no_auth_mocks(project_slug: str) -> str:
    """mocks.dart without AuthRepository/DevAuthService/KeycloakAuthService imports."""
    return (
        "import 'package:dio/dio.dart';\n"
        "import 'package:" + project_slug + "/src/api/generated/export.dart';\n"
        "import 'package:" + project_slug + "/src/features/home/data/home_repository.dart';\n"
        "import 'package:mocktail/mocktail.dart';\n"
        "\n"
        "class MockDio extends Mock implements Dio {}\n"
        "\n"
        "class MockHomeRepository extends Mock implements HomeRepository {}\n"
        "\n"
        "class MockRequestInterceptorHandler extends Mock\n"
        "    implements RequestInterceptorHandler {}\n"
        "\n"
        "class MockErrorInterceptorHandler extends Mock\n"
        "    implements ErrorInterceptorHandler {}\n"
        "\n"
        "class MockHomeClient extends Mock implements HomeClient {}\n"
        "\n"
        "class MockHealthClient extends Mock implements HealthClient {}\n"
    )


_NO_AUTH_HOME_PAGE = """\
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../theme/design_tokens.dart';
import 'widgets/health_status_card.dart';
import 'widgets/info_card.dart';
import 'widgets/quick_actions_card.dart';

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);

    return Scaffold(
      body: ListView(
        padding: const EdgeInsets.all(DesignTokens.p16),
        children: [
          Text(
            'Welcome back!',
            style: theme.textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: DesignTokens.p4),
          Text(
            "Here's an overview of your workspace.",
            style: theme.textTheme.bodyMedium?.copyWith(
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: DesignTokens.p24),
          const QuickActionsCard(),
          const SizedBox(height: DesignTokens.p16),
          const InfoCard(),
          const SizedBox(height: DesignTokens.p16),
          const HealthStatusCard(),
        ],
      ),
    );
  }
}
"""


def _strip_between(text: str, start_marker: str, end_marker: str, inclusive: bool = True) -> str:
    """Remove the substring between ``start_marker`` and ``end_marker`` (inclusive by default)."""
    i = text.find(start_marker)
    if i < 0:
        return text
    j = text.find(end_marker, i + len(start_marker))
    if j < 0:
        return text
    if inclusive:
        return text[:i] + text[j + len(end_marker):]
    return text[:i + len(start_marker)] + text[j:]


def _drop_import_line(text: str, needle: str) -> str:
    """Remove the full line containing ``needle`` (including trailing newline)."""
    out_lines = [line for line in text.splitlines(keepends=True) if needle not in line]
    return "".join(out_lines)


def _patch_app_sidebar_no_auth(path: Path) -> None:
    """Drop the ProfileMenu footer from AppSidebar when auth is disabled."""
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    content = _drop_import_line(content, "'profile_menu.dart'")
    content = content.replace(
        "          footer: ProfileMenu(isExpanded: data.isOpen),\n",
        "",
    )
    path.write_text(content, encoding="utf-8")


def _patch_working_area_header_no_chat(path: Path) -> None:
    """Drop the ChatButton from WorkingAreaHeader when chat is disabled."""
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    content = _drop_import_line(content, "chat_button.dart")
    content = content.replace("          ChatButton(),\n", "")
    path.write_text(content, encoding="utf-8")


def _patch_app_layout_shell_no_chat(path: Path) -> None:
    """Remove the inline ChatPanel block + endDrawer + unused locals.

    Post-patch the file has no chat machinery left, so the three variables
    (``availableWidth``, ``maxChatWidth``, ``chatWidth``) that fed the inline
    chat and the ``layoutExt`` used only by the medium endDrawer all become
    unused — ``flutter analyze`` flags them as warnings. Drop them too so the
    post-patch file passes analyze cleanly.
    """
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    content = _drop_import_line(content, "chat/presentation/chat_panel.dart")
    content = _drop_import_line(content, "vertical_split_handle.dart")
    # Drop the inline chat block in _ExpandedLayoutState.
    content = _strip_between(
        content,
        "                // Splitter + Chat panel (explicit width)",
        "                ],",
    )
    # Drop the endDrawer arg in _MediumLayout (3 lines).
    content = content.replace(
        "      endDrawer: SizedBox(\n"
        "        width: layoutExt.chatDrawerWidth,\n"
        "        child: const Drawer(child: ChatPanel(isFullScreen: true)),\n"
        "      ),\n",
        "",
    )
    # _MediumLayout used layoutExt only for endDrawer width — now unused.
    # The suffix (``body: Row(\n``) disambiguates from _CompactLayout, which
    # still uses layoutExt.headerHeight and must keep its declaration.
    content = content.replace(
        "    final layoutExt =\n"
        "        Theme.of(context).extension<LayoutThemeExtension>()!;\n\n"
        "    return Scaffold(\n"
        "      body: Row(\n",
        "    return Scaffold(\n"
        "      body: Row(\n",
    )
    # _ExpandedLayoutState's three locals (availableWidth / maxChatWidth /
    # chatWidth) existed solely for the inline chat's dynamic sizing. Remove
    # the whole block from the LayoutBuilder.
    content = content.replace(
        "      builder: (context, constraints) {\n"
        "        final availableWidth =\n"
        "            constraints.maxWidth - layout.effectiveSidebarWidth;\n"
        "        final maxChatWidth = availableWidth - layoutExt.minMainAreaWidth;\n"
        "        final chatWidth = layout.chatInline\n"
        "            ? (layout.chatWidthRatio * availableWidth).clamp(\n"
        "                layoutExt.minChatWidth,\n"
        "                maxChatWidth.clamp(layoutExt.minChatWidth, double.infinity),\n"
        "              )\n"
        "            : 0.0;\n\n"
        "        return Material(\n",
        "      builder: (context, constraints) {\n"
        "        return Material(\n",
    )
    # `final layout = widget.layout;` and `final layoutExt = theme.extension<...>()!;`
    # are no longer referenced after the chat-sizing block is gone.
    content = content.replace(
        "  Widget build(BuildContext context) {\n"
        "    final layout = widget.layout;\n"
        "    final theme = Theme.of(context);\n"
        "    final layoutExt = theme.extension<LayoutThemeExtension>()!;\n",
        "  Widget build(BuildContext context) {\n"
        "    final theme = Theme.of(context);\n",
    )
    path.write_text(content, encoding="utf-8")


def remove_optional_files():
    removed = []
    if not INCLUDE_AUTH:
        lib_src = PROJECT_DIR / "lib" / "src"
        test_root = PROJECT_DIR / "test"
        test_src = test_root / "src"
        # Directory / file deletions — everything auth-specific on the source side.
        remove_path(lib_src / "features" / "auth")
        remove_path(lib_src / "features" / "profile")
        remove_path(lib_src / "shared" / "layout" / "profile_menu.dart")
        remove_path(lib_src / "shared" / "providers" / "current_user_provider.dart")
        # flutter_secure_storage is gated off in pubspec when auth=false, so
        # this provider's import chain fails to compile.
        remove_path(lib_src / "core" / "storage" / "secure_storage_provider.dart")
        remove_path(lib_src / "core" / "storage" / "secure_storage_provider.g.dart")
        # Auth-paired test scaffolding.
        remove_path(test_src / "features" / "auth")
        remove_path(test_src / "features" / "profile")
        remove_path(test_src / "api" / "client" / "auth_interceptor_test.dart")
        remove_path(test_src / "core" / "storage")  # provider tests depend on the secure_storage pkg
        remove_path(test_root / "fixtures" / "user.dart")
        # mocks.dart is shared by non-auth tests (home, error-interceptor) so
        # swap it for a variant that omits the auth mock classes + imports.
        write_file(test_root / "helpers" / "mocks.dart", _no_auth_mocks(PROJECT_SLUG))
        # Rewrites: router, interceptor, home page drop the auth-specific wiring.
        write_file(lib_src / "routing" / "app_router.dart", _NO_AUTH_APP_ROUTER)
        write_file(lib_src / "api" / "client" / "auth_interceptor.dart", _NO_AUTH_INTERCEPTOR)
        write_file(lib_src / "features" / "home" / "presentation" / "home_page.dart", _NO_AUTH_HOME_PAGE)
        # Sidebar drops its ProfileMenu footer.
        _patch_app_sidebar_no_auth(lib_src / "shared" / "layout" / "app_sidebar.dart")
        removed.append("auth")
    if not INCLUDE_CHAT:
        lib_src = PROJECT_DIR / "lib" / "src"
        test_src = PROJECT_DIR / "test" / "src"
        remove_path(lib_src / "features" / "chat")
        remove_path(lib_src / "shared" / "widgets" / "chat_button.dart")
        remove_path(test_src / "features" / "chat")
        _patch_app_layout_shell_no_chat(lib_src / "shared" / "layout" / "app_layout_shell.dart")
        _patch_working_area_header_no_chat(lib_src / "shared" / "layout" / "working_area_header.dart")
        removed.append("chat")
    if not INCLUDE_OPENAPI:
        remove_path(PROJECT_DIR / "lib" / "src" / "api")
        remove_path(PROJECT_DIR / "openapi")
        for f in ["swagger_parser.yaml", "scripts/fetch_openapi.sh", "scripts/generate_api.sh"]:
            remove_path(PROJECT_DIR / f)
        removed.append("openapi")
    if removed:
        print("  Removed optional: %s" % ", ".join(removed))
    else:
        print("  All components enabled")


# -- WS2: multi-backend awareness ---------------------------------------------

def patch_feature_repository_paths(features) -> None:
    """Prefix repository HTTP paths per backend for multi-backend deployments.

    Each generated `lib/src/features/{name}/data/{name}_repository.dart` emits
    paths like `/items`. For multi-backend deployments routed through Traefik,
    rewrite to `/api/{backend}/v1/items` so requests reach the right service.
    Single-backend projects (the common case) skip this and keep the existing
    `api_base_url`-relative paths.
    """
    if not IS_MULTI_BACKEND:
        return
    for feat in features:
        backend = FEATURE_TO_BACKEND.get(feat, DEFAULT_BACKEND)
        repo_path = (
            PROJECT_DIR / "lib" / "src" / "features" / feat / "data"
            / ("%s_repository.dart" % feat)
        )
        if not repo_path.exists():
            continue
        text = repo_path.read_text(encoding="utf-8")
        # Rewrite the literal '/{plural}' path strings the repo template emits.
        replacements = [
            ("'/%s'" % feat, "'/api/%s/v1/%s'" % (backend, feat)),
            ("'/%s/$id'" % feat, "'/api/%s/v1/%s/$id'" % (backend, feat)),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        repo_path.write_text(text, encoding="utf-8")
        print("  Patched %s -> /api/%s/v1/%s" % (repo_path.relative_to(PROJECT_DIR), backend, feat))


def write_backend_routes_constant(features) -> None:
    """Write a `lib/src/core/config/backend_routes.dart` constant for runtime use.

    Always emitted (even single-backend) so application code has a single source of
    truth for which backend each entity routes through, instead of hardcoding strings.
    """
    if not features:
        return
    config_dir = PROJECT_DIR / "lib" / "src" / "core" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for feat in features:
        backend = FEATURE_TO_BACKEND.get(feat, DEFAULT_BACKEND)
        entries.append("  '%s': '%s'," % (feat, backend))
    content = (
        "// Generated by forge — do not edit by hand.\n"
        "//\n"
        "// Maps each scaffolded feature to its owning backend service. Repositories\n"
        "// can read this map to construct routes like `/api/${backend}/v1/${entity}`\n"
        "// for multi-backend deployments behind a Traefik-style reverse proxy.\n"
        "const Map<String, String> backendRoutes = {\n"
        + "\n".join(entries)
        + "\n};\n"
    )
    (config_dir / "backend_routes.dart").write_text(content, encoding="utf-8")
    print("  Generated lib/src/core/config/backend_routes.dart (%d entries)" % len(features))


# -- Main ----------------------------------------------------------------------

def main():
    print()
    print("=" * 60)
    print("  Setting up: %s" % PROJECT_NAME)
    print("=" * 60)
    print()

    print("> Scaffolding platform files")
    scaffold_flutter_project()
    print()

    print("> Generating features")
    features = generate_features()
    print()

    print("> Configuring project")
    generate_import_lint(features)
    generate_readme(features)
    patch_web_files()
    patch_feature_repository_paths(features)
    write_backend_routes_constant(features)
    remove_optional_files()
    print()

    print("> Building project")
    flutter_bin = shutil.which("flutter")
    dart_bin = shutil.which("dart")

    if not flutter_bin:
        print("  Flutter CLI not found. Run manually:")
        print("    flutter pub get")
        print("    dart run build_runner build --delete-conflicting-outputs")
        print()
        return

    install_ok = run_command([flutter_bin, "pub", "get"], "Installing dependencies (flutter pub get)", timeout=300)
    if not install_ok:
        return

    if dart_bin:
        run_command([dart_bin, "run", "build_runner", "build", "--delete-conflicting-outputs"],
                    "Running code generation (build_runner)", timeout=600)

    print()
    print("> Validating project")
    run_command([flutter_bin, "analyze"], "Running analysis (flutter analyze)")
    run_command([flutter_bin, "test"], "Running tests (flutter test)")

    git_bin = shutil.which("git")
    if git_bin:
        print()
        print("> Initializing repository")
        run_command([git_bin, "init"], "git init")
        run_command([git_bin, "add", "."], "git add .")
        run_command([git_bin, "commit", "-m", "Initial project from template"], "git commit")

    print()
    print("=" * 60)
    print("  Project ready: %s" % PROJECT_DIR)
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()

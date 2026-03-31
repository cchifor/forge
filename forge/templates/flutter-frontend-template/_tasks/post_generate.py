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
    parser.add_argument("--org-name", default="com.example")
    parser.add_argument("--features", default="items")
    parser.add_argument("--include-auth", default="True")
    parser.add_argument("--include-chat", default="True")
    parser.add_argument("--include-openapi", default="True")
    parser.add_argument("--description", default="A Flutter application")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--api-base-url", default="http://localhost:5000/api/v1")
    return parser.parse_args()

_args = parse_args()
PROJECT_SLUG = _args.project_slug
PROJECT_DIR = Path.cwd() / PROJECT_SLUG
PACKAGE_NAME = _args.project_slug
PROJECT_NAME = _args.project_name
ORG_NAME = _args.org_name
FEATURES = _args.features
INCLUDE_AUTH = _args.include_auth.lower() == "true"
INCLUDE_CHAT = _args.include_chat.lower() == "true"
INCLUDE_OPENAPI = _args.include_openapi.lower() == "true"
DESCRIPTION = _args.description
VERSION = _args.version
API_BASE_URL = _args.api_base_url

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

    if INCLUDE_AUTH:
        sso = PROJECT_DIR / "web" / "silent-check-sso.html"
        sso.parent.mkdir(parents=True, exist_ok=True)
        sso.write_text(
            '<!doctype html>\n<html>\n<body>\n<script>\n'
            '  parent.postMessage(location.href, location.origin);\n'
            '</script>\n</body>\n</html>\n',
            encoding="utf-8",
        )


def generate_readme(features):
    feature_rows = "| **Home** | Dashboard with service info and health status | Built-in |\n"
    if INCLUDE_AUTH:
        feature_rows += "| **Auth** | OAuth2/Keycloak login with dev mode | Built-in |\n"
    feature_rows += "| **Profile** | User profile from JWT claims | Built-in |\n"
    feature_rows += "| **Settings** | Theme mode, color scheme, OLED dark mode | Built-in |\n"
    if INCLUDE_CHAT:
        feature_rows += "| **Chat** | AI chat sidebar with split-screen | Built-in |\n"
    for f in features:
        ctx = make_feature_context(f, PACKAGE_NAME)
        feature_rows += "| **%s** | CRUD operations for %s | Generated |\n" % (ctx["Plural"], ctx["plural"])

    feature_tree = ""
    for f in features:
        ctx = make_feature_context(f, PACKAGE_NAME)
        feature_tree += "\n### %s (`features/%s/`)\n```\n%s/\n  %s_routes.dart\n  data/%s_repository.dart\n  domain/%s_query_params.dart\n  presentation/\n    %s_controller.dart\n    %s_list_page.dart\n    %s_detail_page.dart\n    %s_create_page.dart\n    widgets/\n      %s_card.dart\n      %s_form.dart\n```\n" % (
            ctx["Plural"], ctx["plural"], ctx["plural"], ctx["plural"], ctx["plural"], ctx["plural"],
            ctx["plural"], ctx["plural"], ctx["singular"], ctx["singular"], ctx["singular"], ctx["singular"])

    readme = "# %s\n\n%s\n\n## Quick Start\n\n```bash\ncd %s\nflutter run --dart-define=AUTH_DISABLED=true --dart-define=API_BASE_URL=%s\n```\n\n## Features\n\n| Feature | Description | Source |\n|---------|-------------|--------|\n%s\n## Feature Modules\n%s\n## Testing\n\n```bash\nflutter test\n```\n\n## Project Info\n\n- **Version**: %s\n- **Package**: `%s`\n" % (
        PROJECT_NAME, DESCRIPTION, PROJECT_SLUG, API_BASE_URL,
        feature_rows, feature_tree, VERSION, PACKAGE_NAME)

    write_file(PROJECT_DIR / "README.md", readme)
    print("  Generated README.md")


def remove_optional_files():
    removed = []
    if not INCLUDE_AUTH:
        remove_path(PROJECT_DIR / "lib" / "src" / "features" / "auth")
        removed.append("auth")
    if not INCLUDE_CHAT:
        remove_path(PROJECT_DIR / "lib" / "src" / "features" / "chat")
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

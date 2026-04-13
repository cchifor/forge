"""Post-generation script for the E2E platform template.

Reads Copier-rendered answers and generates per-feature spec files
in the tests/ directory, following the same pattern as Vue/Svelte
frontend templates.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def make_feature_context(plural_name: str) -> dict:
    """Derive all naming variants from a plural feature name."""
    singular = (
        plural_name.rstrip("s")
        if plural_name.endswith("s") and len(plural_name) > 1
        else plural_name
    )
    return {
        "plural": plural_name,
        "singular": singular,
        "Plural": plural_name[0].upper() + plural_name[1:],
        "Singular": singular[0].upper() + singular[1:],
    }


def main() -> None:
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent

    # 1. Read Copier-rendered answers
    answers_path = script_dir / "answers.json"
    if not answers_path.exists():
        print("  [!!] answers.json not found, skipping spec generation")
        return

    answers = json.loads(answers_path.read_text(encoding="utf-8"))
    features_raw = answers.get("features", "items")
    include_auth = answers.get("include_auth", False)

    features = [f.strip() for f in features_raw.split(",") if f.strip()]

    # 2. Import spec templates
    sys.path.insert(0, str(script_dir))
    from spec_templates import AUTH_SPEC_TEMPLATE, FEATURE_SPEC_TEMPLATE

    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)

    # 3. Generate per-feature spec files
    for feature in features:
        ctx = make_feature_context(feature)
        spec_content = FEATURE_SPEC_TEMPLATE.format(**ctx)
        spec_path = tests_dir / f"{feature}.spec.ts"
        spec_path.write_text(spec_content, encoding="utf-8")
        print(f"  [ok] Generated tests/{feature}.spec.ts")

    # 4. Generate auth spec if enabled
    if include_auth:
        auth_content = AUTH_SPEC_TEMPLATE
        auth_path = tests_dir / "auth.spec.ts"
        auth_path.write_text(auth_content, encoding="utf-8")
        print("  [ok] Generated tests/auth.spec.ts")
    else:
        # Remove auth directory when auth is not included
        auth_dir = project_dir / "e2e-platform" / "auth"
        if auth_dir.exists():
            shutil.rmtree(str(auth_dir))

    # 5. Remove .gitkeep if specs were generated
    gitkeep = tests_dir / ".gitkeep"
    if gitkeep.exists() and any(tests_dir.glob("*.spec.ts")):
        gitkeep.unlink()

    # 6. Install npm dependencies (skip gracefully if Node.js not available)
    pkg_json = project_dir / "package.json"
    if pkg_json.exists():
        try:
            subprocess.run(
                ["npm", "install"],
                cwd=str(project_dir),
                capture_output=True,
                timeout=120,
            )
            print("  [ok] npm install")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("  [!!] npm install skipped (Node.js not available)")

    # 7. Clean up _tasks directory
    shutil.rmtree(str(script_dir))


if __name__ == "__main__":
    main()

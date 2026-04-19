"""Parity tests for the three shell completion scripts.

Every long ``--flag`` argparse knows about must appear in every script
that ``forge --completion <shell>`` prints. The scripts are generated
by introspecting ``_build_parser()`` (in ``forge/cli.py``), so these
tests primarily guard against future drift -- a flag added without
re-running the generator, or an action tagged with an exotic
``option_strings`` shape the introspector didn't handle.
"""

from __future__ import annotations

import pytest

from forge import cli


@pytest.fixture(scope="module")
def parser():
    return cli._build_parser()


@pytest.fixture(scope="module")
def long_flags(parser) -> list[str]:
    return [o for a in parser._actions for o in a.option_strings if o.startswith("--")]


class TestBashCompletion:
    def test_every_long_flag_present(self, long_flags: list[str]) -> None:
        script = cli._BASH_COMPLETION
        missing = [f for f in long_flags if f not in script]
        assert not missing, f"bash completion missing: {missing}"

    def test_choice_flags_have_case_branch(self, parser) -> None:
        """Every argparse action with ``choices=`` should have a case
        entry that completes those values."""
        script = cli._BASH_COMPLETION
        for action in parser._actions:
            if not action.choices:
                continue
            long_opts = [o for o in action.option_strings if o.startswith("--")]
            if not long_opts:
                continue
            for opt in long_opts:
                # The generator groups flags by their pattern, so check
                # that the flag appears in at least one ``compgen -W`` case.
                assert f"{opt})" in script or f"{opt}|" in script, (
                    f"bash completion missing case branch for {opt}"
                )

    def test_shell_syntax_looks_valid(self) -> None:
        """Sanity: script declares the completion function and registers it."""
        script = cli._BASH_COMPLETION
        assert "_forge_completions()" in script
        assert "complete -F _forge_completions forge" in script


class TestZshCompletion:
    def test_every_long_flag_present(self, long_flags: list[str]) -> None:
        script = cli._ZSH_COMPLETION
        missing = [f for f in long_flags if f not in script]
        assert not missing, f"zsh completion missing: {missing}"

    def test_compdef_header(self) -> None:
        assert cli._ZSH_COMPLETION.startswith("#compdef forge")

    def test_arguments_call_present(self) -> None:
        assert "_arguments" in cli._ZSH_COMPLETION


class TestFishCompletion:
    def test_every_long_flag_present(self, long_flags: list[str]) -> None:
        script = cli._FISH_COMPLETION
        # Fish uses ``-l <flag-without-dashes>``; strip the leading --
        for flag in long_flags:
            needle = f" -l {flag[2:]} "
            # line-terminal tail also counts (last token on a line has no trailing space)
            assert needle in script or script.rstrip().endswith(f" -l {flag[2:]}"), (
                f"fish completion missing entry for {flag}"
            )

    def test_choice_flags_have_xa(self, parser) -> None:
        script = cli._FISH_COMPLETION
        for action in parser._actions:
            if not action.choices:
                continue
            longs = [o[2:] for o in action.option_strings if o.startswith("--")]
            if not longs:
                continue
            # Only the primary long flag (first in action.option_strings)
            # carries the -xa. Extras only get a -d line.
            primary = longs[0]
            import re

            pattern = re.compile(rf'-l {re.escape(primary)}\b.*-xa "')
            assert pattern.search(script), (
                f"fish completion missing -xa choice list for --{primary}"
            )


class TestCompletionDispatch:
    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_print_completion_emits_script(
        self, shell: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            cli._print_completion(shell)
        assert excinfo.value.code == 0
        out = capsys.readouterr().out
        assert out, f"{shell} completion produced empty output"
        # Each shell should mention the tool name at least once.
        assert "forge" in out

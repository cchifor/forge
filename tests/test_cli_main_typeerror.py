"""WS-3.3(b): the generate() TypeError fallback must not mask real bugs.

main() calls generate() with the modern kwargs (dry_run/report/keep_partial)
and falls back to the legacy signature on TypeError. A blanket
``except TypeError`` also swallows genuine bugs inside generate() (or a
plugin shim) that happen to raise TypeError — turning a real stack trace
into a silent, confusing second call. The fallback must fire ONLY for an
argument-binding signature mismatch; any other TypeError must surface.
"""

from __future__ import annotations

import pytest

from forge.cli.main import _is_generate_signature_mismatch


def _typeerror_from_bad_call() -> TypeError:
    """A real TypeError produced by Python's argument binder, not a fake."""

    def legacy(config, *, quiet=False):
        return None

    try:
        legacy(object(), quiet=False, dry_run=True, report=None, keep_partial=False)  # type: ignore[call-arg]
    except TypeError as exc:
        return exc
    raise AssertionError("expected the bad call to raise TypeError")


def test_unexpected_keyword_is_a_signature_mismatch():
    exc = _typeerror_from_bad_call()
    assert _is_generate_signature_mismatch(exc) is True


@pytest.mark.parametrize(
    "msg",
    [
        # Only the modern kwargs main() actually passes count as a
        # signature mismatch — those are the args an older generate() rejects.
        "generate() got an unexpected keyword argument 'dry_run'",
        "generate() got an unexpected keyword argument 'report'",
        "generate() got an unexpected keyword argument 'keep_partial'",
    ],
)
def test_arg_binding_messages_are_signature_mismatches(msg):
    assert _is_generate_signature_mismatch(TypeError(msg)) is True


@pytest.mark.parametrize(
    "msg",
    [
        "unsupported operand type(s) for +: 'int' and 'str'",
        "'NoneType' object is not subscriptable",
        "can only concatenate str (not \"int\") to str",
        "argument of type 'int' is not iterable",
        # A genuine TypeError from a HELPER inside generate()'s body that
        # happens to mention an unexpected keyword must NOT be swallowed
        # (codex finding): the matcher keys on our own kwarg names only.
        "helper() got an unexpected keyword argument 'foo'",
        "build_thing() got an unexpected keyword argument 'verbose'",
        # Positional-count errors can't come from main()'s call shape
        # (config is always passed positionally + is required), so they are
        # real bugs, not a legacy-signature fallback trigger.
        "generate() takes 1 positional argument but 2 were given",
        "generate() missing 1 required positional argument: 'config'",
    ],
)
def test_real_bugs_are_not_signature_mismatches(msg):
    # A genuine TypeError from inside generate()'s body must NOT be treated
    # as a signature mismatch — it should surface, not trigger a silent retry.
    assert _is_generate_signature_mismatch(TypeError(msg)) is False

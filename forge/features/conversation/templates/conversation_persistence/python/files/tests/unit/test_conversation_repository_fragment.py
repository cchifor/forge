"""Fragment smoke tests for `conversation_persistence`.

Asserts the repository refuses to instantiate without a valid Account —
the structural guarantee the A1.2 fix introduced. Running against the
generated project catches regressions when a future fragment change
removes the guard.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import PermissionDeniedError
from app.data.repositories.conversation_repository import ConversationRepository
from service.domain.account import Account


def test_refuses_null_account() -> None:
    with pytest.raises(PermissionDeniedError, match="authenticated tenant"):
        ConversationRepository(session=None, account=None)  # type: ignore[arg-type]


def test_refuses_missing_customer_id() -> None:
    acct = Account(customer_id=None, user_id=uuid.uuid4())
    with pytest.raises(PermissionDeniedError):
        ConversationRepository(session=None, account=acct)  # type: ignore[arg-type]


def test_refuses_missing_user_id() -> None:
    acct = Account(customer_id=uuid.uuid4(), user_id=None)
    with pytest.raises(PermissionDeniedError):
        ConversationRepository(session=None, account=acct)  # type: ignore[arg-type]


def test_valid_account_constructs() -> None:
    cid = uuid.uuid4()
    uid = uuid.uuid4()
    repo = ConversationRepository(session=None, account=Account(customer_id=cid, user_id=uid))  # type: ignore[arg-type]
    assert repo.customer_id == cid
    assert repo.user_id == uid


def test_assert_owned_rejects_cross_tenant() -> None:
    mine = uuid.uuid4()
    theirs = uuid.uuid4()
    repo = ConversationRepository(  # type: ignore[arg-type]
        session=None, account=Account(customer_id=mine, user_id=uuid.uuid4())
    )

    class Row:
        pass

    row = Row()
    row.customer_id = theirs  # type: ignore[attr-defined]
    with pytest.raises(PermissionDeniedError, match="another tenant"):
        repo.assert_owned(row)

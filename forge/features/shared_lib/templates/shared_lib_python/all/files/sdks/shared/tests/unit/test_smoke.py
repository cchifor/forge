"""Verify the shared package imports without errors."""


def test_import_shared():
    import shared
    assert hasattr(shared, "__all__")


def test_import_base_domain():
    from shared.domain.base import BaseDomainModel
    assert BaseDomainModel is not None

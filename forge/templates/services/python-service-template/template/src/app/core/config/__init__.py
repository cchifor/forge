from typing import TYPE_CHECKING

from .loader import Settings

_settings_instance: Settings | None = None


def get_settings() -> Settings:
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


class SettingsProxy:
    """Delegates attribute access to the actual Settings instance.
    Prevents ConfigLoader from running at import time."""

    def __getattr__(self, name):
        return getattr(get_settings(), name)


settings = SettingsProxy()

if TYPE_CHECKING:
    settings = Settings()  # type: ignore[assignment]

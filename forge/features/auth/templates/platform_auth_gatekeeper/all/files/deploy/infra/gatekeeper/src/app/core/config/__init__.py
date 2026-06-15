from typing import TYPE_CHECKING

from .loader import Settings

# 1. Global storage for the settings instance
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """
    Lazy loader: Instantiates Settings only when called.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


# Lazy Proxy Implementation
class SettingsProxy:
    """
    Delegates attribute access to the actual Settings instance.
    This prevents the ConfigLoader from running at import time.
    """

    def __getattr__(self, name):
        return getattr(get_settings(), name)


# Export the proxy
settings = SettingsProxy()

# Type hint for IDE autocompletion support
if TYPE_CHECKING:
    settings = Settings()

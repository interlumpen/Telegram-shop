import pytest
from unittest.mock import patch

from bot.i18n.main import get_locale, localize
from bot.i18n.strings import DEFAULT_LOCALE


@pytest.fixture(autouse=True)
def clear_locale_cache():
    """get_locale is lru_cached — every case needs a cold cache on both sides."""
    get_locale.cache_clear()
    yield
    get_locale.cache_clear()


def _with_locale(value):
    """Patch the configured locale for one call."""
    return patch('bot.i18n.main.EnvKeys', **{"BOT_LOCALE": value})


class TestGetLocale:

    @pytest.mark.parametrize("configured,expected", [
        ("ru", "ru"),
        ("  RU  ", "ru"),          # stripped and lowered
        ("xx", DEFAULT_LOCALE),    # unknown locale falls back
    ])
    def test_resolution(self, configured, expected):
        with _with_locale(configured):
            assert get_locale() == expected


class TestLocalize:

    def test_existing_key(self):
        with _with_locale("ru"):
            # Returns the translation, not the key itself.
            assert localize("btn.shop") != "btn.shop"

    def test_missing_key_returns_key(self):
        with _with_locale("ru"):
            assert localize("nonexistent.key.that.does.not.exist") \
                   == "nonexistent.key.that.does.not.exist"

    def test_format_with_kwargs(self):
        with _with_locale("ru"):
            result = localize("profile.caption", id=12345, name="TestUser")
        assert "12345" in result
        assert "TestUser" in result

    def test_format_error_returns_unformatted(self):
        # profile.caption expects {id} and {name} — wrong kwargs must not crash.
        with _with_locale("ru"):
            result = localize("profile.caption", wrong_key="value")
        assert "{id}" in result and "{name}" in result

    def test_localize_returns_nonempty_string(self):
        with _with_locale("ru"):
            result = localize("btn.back")
        assert isinstance(result, str)
        assert len(result) > 0

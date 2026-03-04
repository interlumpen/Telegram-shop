import os
from abc import ABC
from typing import Final
from urllib.parse import quote_plus


class EnvKeys(ABC):
    """Secure environment configuration with validation"""

    @staticmethod
    def _get_required(key: str) -> str:
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Missing required environment variable: {key}")
        return val

    @staticmethod
    def _get_optional(key: str, default: str = "") -> str:
        return os.getenv(key, default)

    # Telegram
    TOKEN: Final = _get_required('TOKEN')
    OWNER_ID: Final = int(_get_required('OWNER_ID'))

    # Database
    POSTGRES_DB: Final = _get_required("POSTGRES_DB")
    POSTGRES_USER: Final = _get_required("POSTGRES_USER")
    POSTGRES_PASSWORD: Final = _get_required("POSTGRES_PASSWORD")
    DB_PORT: Final = int(_get_optional("DB_PORT", "5432"))
    DB_DRIVER: Final = _get_optional("DB_DRIVER", "postgresql+psycopg")
    POSTGRES_HOST: Final = _get_optional("POSTGRES_HOST", "localhost")

    # Redis
    REDIS_ENABLED: Final = _get_optional("REDIS_ENABLED", "1")
    REDIS_HOST: Final = _get_optional("REDIS_HOST", "localhost")
    REDIS_PORT: Final = int(_get_optional("REDIS_PORT", "6379"))
    REDIS_DB: Final = int(_get_optional("REDIS_DB", "0"))
    REDIS_PASSWORD: Final = _get_optional("REDIS_PASSWORD", "")

    # Payments
    TELEGRAM_PROVIDER_TOKEN: Final = _get_optional("TELEGRAM_PROVIDER_TOKEN", "")
    CRYPTO_PAY_TOKEN: Final = _get_optional("CRYPTO_PAY_TOKEN", "")
    STARS_PER_VALUE: Final = float(_get_optional("STARS_PER_VALUE", "0.91"))
    REFERRAL_PERCENT: Final = int(_get_optional("REFERRAL_PERCENT", "0"))
    PAY_CURRENCY: Final = _get_optional("PAY_CURRENCY", "RUB")
    PAYMENT_TIME: Final = int(_get_optional("PAYMENT_TIME", "1800"))
    MIN_AMOUNT: Final = int(_get_optional("MIN_AMOUNT", "20"))
    MAX_AMOUNT: Final = int(_get_optional("MAX_AMOUNT", "10000"))

    # Links / UI
    CHANNEL_URL: Final = _get_optional("CHANNEL_URL", "")
    CHANNEL_ID: Final = _get_optional("CHANNEL_ID", "")
    HELPER_ID: Final = _get_optional("HELPER_ID", "")
    RULES: Final = _get_optional("RULES", "")

    # Locale & logs
    BOT_LOCALE: Final = _get_optional("BOT_LOCALE", "ru")
    BOT_LOGFILE: Final = _get_optional("BOT_LOGFILE", "logs/bot.log")
    BOT_AUDITFILE: Final = _get_optional("BOT_AUDITFILE", "logs/audit.log")
    LOG_TO_STDOUT: Final = _get_optional("LOG_TO_STDOUT", "1")
    LOG_TO_FILE: Final = _get_optional("LOG_TO_FILE", "1")
    DEBUG: Final = _get_optional("DEBUG", "0")

    # Web admin panel
    ADMIN_HOST: Final = _get_optional("ADMIN_HOST", _get_optional("MONITORING_HOST", "localhost"))
    ADMIN_PORT: Final = int(_get_optional("ADMIN_PORT", _get_optional("MONITORING_PORT", "9090")))
    ADMIN_USERNAME: Final = _get_optional("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: Final = _get_optional("ADMIN_PASSWORD", "admin")
    SECRET_KEY: Final = _get_optional("SECRET_KEY", "change-me-in-production")

    DATABASE_URL: Final = f"{DB_DRIVER}://{POSTGRES_USER}:{quote_plus(POSTGRES_PASSWORD)}@{POSTGRES_HOST}:{DB_PORT}/{POSTGRES_DB}"

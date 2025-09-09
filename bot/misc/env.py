import os
from abc import ABC
from typing import Final


class EnvKeys(ABC):
    """Secure environment configuration with validation"""

    # Telegram
    TOKEN: Final = os.environ.get('TOKEN')
    OWNER_ID: Final = os.environ.get('OWNER_ID')

    # Payments
    TELEGRAM_PROVIDER_TOKEN: Final = os.getenv("TELEGRAM_PROVIDER_TOKEN")
    CRYPTO_PAY_TOKEN: Final = os.getenv("CRYPTO_PAY_TOKEN")
    STARS_PER_VALUE: Final = float(os.getenv("STARS_PER_VALUE", "0.91"))
    REFERRAL_PERCENT: Final = int(os.getenv("REFERRAL_PERCENT", 0))
    PAY_CURRENCY: Final = os.getenv("PAY_CURRENCY", "RUB")
    PAYMENT_TIME: Final = int(os.getenv("PAYMENT_TIME", 1800))
    MIN_AMOUNT: Final = int(os.getenv("MIN_AMOUNT", 20))
    MAX_AMOUNT: Final = int(os.getenv("MAX_AMOUNT", 10_000))

    # Links / UI
    CHANNEL_URL: Final = os.getenv("CHANNEL_URL")
    HELPER_ID: Final = os.getenv("HELPER_ID")
    RULES: Final = os.getenv("RULES")

    # Locale & logs
    BOT_LOCALE: Final = os.getenv("BOT_LOCALE", "ru")
    BOT_LOGFILE: Final = os.getenv("BOT_LOGFILE", "bot.log")
    BOT_AUDITFILE: Final = os.getenv("BOT_AUDITFILE", "audit.log")
    LOG_TO_STDOUT: Final = os.getenv("LOG_TO_STDOUT", "1")
    LOG_TO_FILE: Final = os.getenv("LOG_TO_FILE", "1")
    DEBUG: Final = os.getenv("DEBUG", "0")

    # Redis
    REDIS_HOST: Final = os.getenv("REDIS_HOST")
    REDIS_PORT: Final = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: Final = int(os.getenv("REDIS_DB", 0))
    REDIS_PASSWORD: Final = os.getenv("REDIS_PASSWORD")

    # Database (for Docker)
    POSTGRES_DB: Final = os.getenv("POSTGRES_DB")
    POSTGRES_USER: Final = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: Final = os.getenv("POSTGRES_PASSWORD")
    DB_PORT: Final = int(os.getenv("DB_PORT", 5432))
    DB_DRIVER: Final = os.getenv("DB_DRIVER", "postgresql+psycopg2")

    # Database (for manual deploy)
    DATABASE_URL: Final = "postgresql+psycopg2://user:password@localhost:5432/db_name"  # (setup if you deploy manually)

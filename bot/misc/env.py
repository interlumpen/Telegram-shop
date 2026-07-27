import logging
import os
from abc import ABC
from typing import Final
from urllib.parse import quote_plus

_env_logger = logging.getLogger(__name__)

_DEFAULT_ADMIN_PASSWORD = "admin"
_DEFAULT_SECRET_KEY = "change-me-in-production"

# An empty host means "not bound anywhere reachable" as far as this check cares.
_LOOPBACK_HOSTS = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})


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
    POSTGRES_HOST: Final = _get_optional("POSTGRES_HOST", "localhost")
    DB_POOL_SIZE: Final = int(_get_optional("DB_POOL_SIZE", "10"))
    DB_MAX_OVERFLOW: Final = int(_get_optional("DB_MAX_OVERFLOW", "20"))

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
    REVIEWS_ENABLED: Final = _get_optional("REVIEWS_ENABLED", "1")

    # Web admin panel
    ADMIN_HOST: Final = _get_optional("ADMIN_HOST", _get_optional("MONITORING_HOST", "localhost"))
    ADMIN_PORT: Final = int(_get_optional("ADMIN_PORT", _get_optional("MONITORING_PORT", "9090")))
    ADMIN_USERNAME: Final = _get_optional("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: Final = _get_optional("ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
    SECRET_KEY: Final = _get_optional("SECRET_KEY", _DEFAULT_SECRET_KEY)
    ADMIN_COOKIE_SECURE: Final = _get_optional("ADMIN_COOKIE_SECURE", "auto")

    # Webhook
    WEBHOOK_ENABLED: Final = _get_optional("WEBHOOK_ENABLED", "0")
    WEBHOOK_URL: Final = _get_optional("WEBHOOK_URL", "")
    WEBHOOK_PATH: Final = _get_optional("WEBHOOK_PATH", "/webhook")
    WEBHOOK_SECRET: Final = _get_optional("WEBHOOK_SECRET", "")
    WEBHOOK_HOST: Final = _get_optional("WEBHOOK_HOST", "0.0.0.0")
    WEBHOOK_PORT: Final = int(_get_optional("WEBHOOK_PORT", "8080"))

    # Cleanup
    AUDIT_RETENTION_DAYS: Final = int(_get_optional("AUDIT_RETENTION_DAYS", "90"))
    PAYMENTS_RETENTION_DAYS: Final = int(_get_optional("PAYMENTS_RETENTION_DAYS", "90"))

    DATABASE_URL: Final = f"postgresql+asyncpg://{POSTGRES_USER}:{quote_plus(POSTGRES_PASSWORD)}@{POSTGRES_HOST}:{DB_PORT}/{POSTGRES_DB}"

    @classmethod
    def panel_is_exposed(cls) -> bool:
        """Whether the admin panel is bound somewhere off-host.

        Webhook mode counts as exposed regardless of the bind address: it is by
        definition a public production deployment, and the placeholder
        credentials have no place in one.
        """
        return (
            cls.ADMIN_HOST.strip().lower() not in _LOOPBACK_HOSTS
            or cls.WEBHOOK_ENABLED == "1"
        )

    @classmethod
    def session_cookie_secure(cls) -> bool:
        """Whether the admin session cookie should be marked Secure."""
        setting = cls.ADMIN_COOKIE_SECURE.strip().lower()
        if setting in ("1", "true", "yes"):
            return True
        if setting in ("0", "false", "no"):
            return False
        return cls.panel_is_exposed()

    @classmethod
    def validate(cls) -> None:
        """Check configuration: fatal on unsafe defaults, warnings otherwise."""
        insecure = []
        if cls.SECRET_KEY == _DEFAULT_SECRET_KEY:
            insecure.append(
                "SECRET_KEY is the shipped default — anyone who can reach the panel "
                "can forge an admin session. Generate one with: "
                'python -c "import secrets; print(secrets.token_hex(32))"'
            )
        if cls.ADMIN_PASSWORD == _DEFAULT_ADMIN_PASSWORD:
            insecure.append(
                "ADMIN_PASSWORD is the shipped default 'admin'. Set a strong password."
            )

        if insecure:
            if cls.panel_is_exposed():
                raise RuntimeError(
                    "Refusing to start: the admin panel is reachable "
                    f"(ADMIN_HOST={cls.ADMIN_HOST!r}, WEBHOOK_ENABLED={cls.WEBHOOK_ENABLED!r}) "
                    "with insecure default credentials.\n  - " + "\n  - ".join(insecure)
                )
            for problem in insecure:
                _env_logger.warning("SECURITY: %s", problem)

        if int(cls.MIN_AMOUNT) >= int(cls.MAX_AMOUNT):
            _env_logger.warning(
                "CONFIG: MIN_AMOUNT (%s) >= MAX_AMOUNT (%s). "
                "Payment amounts will always be rejected.", cls.MIN_AMOUNT, cls.MAX_AMOUNT
            )
        if int(cls.REFERRAL_PERCENT) < 0 or int(cls.REFERRAL_PERCENT) > 99:
            _env_logger.warning(
                "CONFIG: REFERRAL_PERCENT=%s is outside the valid range [0, 99].",
                cls.REFERRAL_PERCENT,
            )

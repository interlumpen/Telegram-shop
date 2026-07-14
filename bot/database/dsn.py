from bot.misc import EnvKeys


def dsn() -> str:
    return EnvKeys.DATABASE_URL

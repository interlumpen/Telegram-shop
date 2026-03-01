import asyncio
import logging
from dotenv import load_dotenv

load_dotenv(encoding='utf-8')

from bot import start_bot

if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped.")

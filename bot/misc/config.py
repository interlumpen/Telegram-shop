from abc import ABC
from typing import Final


class TgConfig(ABC):
    CHANNEL_URL: Final = 'https://t.me/your_channel'
    HELPER_URL: Final = '@YourHelper'
    GROUP_ID: Final = -988765433
    REFERRAL_PERCENT = 5
    PAYMENT_TIME: Final = 1800
    RULES: Final = 'insert your rules here'

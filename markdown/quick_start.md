# QUICK_START
   1. Clone project
   2. Create a virtual venv
   3. Install requirements:
       ```
       pip install --upgrade pip
       pip install -r requirements.txt
       ```
   4. [Setup environment variables:](https://stackoverflow.com/questions/42708389/how-to-set-environment-variables-in-pycharm)

      - [TOKEN](https://telegram.me/BotFather)
      - [OWNER_ID](https://telegram.me/myidbot)
      - [ACCESS_TOKEN](https://pypi.org/project/YooMoney/#access-token)
      - [ACCOUNT_NUMBER](https://pypi.org/project/YooMoney/#account-information)
      - [CRYPTO_PAY_TOKEN](https://help.send.tg/en/articles/10279948-crypto-pay-api#h_020215e6d7)

   5. [Setup config.py](../bot/misc/config.py)
      - CHANNEL_URL - telegram channel link (to disable, set `CHANNEL_URL: Final = 'https://t.me/'`)
      - HELPER_URL -  telegram username for help (to disable, set `HELPER_URL: Final = None`)
      - [GROUP_ID](https://docs.b2core.b2broker.com/how-to-articles/manage-communication-platforms/how-to-get-telegram-chat-group-and-channel-identifiers) -  telegram group ID (to disable, set `GROUP_ID: Final = None`)
      - REFERRAL_PERCENT - percentage of the referral deposit (to disable the referral system, set `REFERRAL_PERCENT = 0`)
      - PAYMENT_TIME - time allotted for payment
      - RULES - rules for using the bot (to disable, set `RULES: Final = None`)

   6. Run run.py

### P.S.
1. Add the bot to the channel and group you have provided and make it an admin
2. To apply latest migration, use 
      ```
      alembic upgrade head
      ```

### [BACK](../README.md)
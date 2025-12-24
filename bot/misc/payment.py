import aiohttp
import json
import math
from typing import Optional

from aiogram import Bot
from aiogram.types import LabeledPrice

from bot.misc import EnvKeys
from bot.i18n import localize

# Currencies without minor units (no cents)
ZERO_DEC_CURRENCIES = {"JPY", "KRW"}


def currency_to_stars(amount_rub: int) -> int:
    """
    Convert currency amount to integer number of Telegram Stars.
    round up (ceil) to avoid undercharging.
    """
    return int(math.ceil(float(amount_rub) * EnvKeys.STARS_PER_VALUE))


async def send_stars_invoice(
        bot: Bot,
        chat_id: int,
        amount: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        payload_extra: Optional[dict] = None,
):
    """
    Send Telegram Stars invoice (currency='XTR', provider_token='').
    LabeledPrice.amount for Stars is a whole number of stars.
    """
    stars = currency_to_stars(amount)

    prices = [LabeledPrice(label=localize("payments.invoice.label.stars", stars=stars), amount=stars)]
    payload = {
        "op": "topup_balance_stars",
        "amount_rub": int(amount),
        "stars": stars,
    }
    if payload_extra:
        payload.update(payload_extra)

    await bot.send_invoice(
        chat_id=chat_id,
        title=title or localize("payments.invoice.title.topup"),
        description=description or localize("payments.invoice.desc.topup.stars", amount=int(amount), currency=EnvKeys.PAY_CURRENCY),
        payload=json.dumps(payload),
        provider_token="",
        currency="XTR",
        prices=prices,
    )


def _minor_units_for(currency: str) -> int:
    """
    Return multiplier to convert major units to minor units.
    """
    return 1 if currency.upper() in ZERO_DEC_CURRENCIES else 100


async def send_fiat_invoice(
        *,
        bot: Bot,
        chat_id: int,
        amount: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
):
    """
    Send invoice via Telegram Payments (fiat provider).
    `amount` is given in major units (e.g., RUB, USD).
    """
    provider_token = EnvKeys.TELEGRAM_PROVIDER_TOKEN
    if not provider_token:
        raise RuntimeError("TELEGRAM_PROVIDER_TOKEN is not set")

    currency = (getattr(EnvKeys, "PAY_CURRENCY", None) or "RUB").upper()
    multiplier = _minor_units_for(currency)
    amount_minor = int(amount) * multiplier

    prices = [
        LabeledPrice(
            label=localize("payments.invoice.label.fiat", amount=int(amount), currency=currency),
            amount=amount_minor,
        )
    ]
    payload = json.dumps({"type": "balance_topup", "amount": int(amount)})

    await bot.send_invoice(
        chat_id=chat_id,
        title=title or localize("payments.invoice.title.topup"),
        description=description or localize("payments.invoice.desc.topup.fiat"),
        payload=payload,
        provider_token=provider_token,
        currency=currency,
        prices=prices,
        request_timeout=60,
    )


class CryptoPayAPIError(Exception):
    """Exception raised when CryptoPay API returns an error."""

    def __init__(self, code: int, name: str, message: str = None):
        self.code = code
        self.name = name
        self.message = message or name
        super().__init__(f"CryptoPay API Error [{code}]: {name}")


class CryptoPayAPI:
    """
    Minimal async client for Crypto Bot API used to create and fetch invoices.
    """

    def __init__(self):
        self.token = EnvKeys.CRYPTO_PAY_TOKEN
        self.base_url = "https://pay.crypt.bot/api"

    async def _request(self, method: str, params: dict) -> dict:
        headers = {"Crypto-Pay-API-Token": self.token}
        url = f"{self.base_url}/{method}"

        if method.startswith("get"):
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        else:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=params, headers=headers) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

        # Check for API-level errors (HTTP 200 but ok=false)
        if not data.get("ok", False):
            error = data.get("error", {})
            raise CryptoPayAPIError(
                code=error.get("code", 0),
                name=error.get("name", "UNKNOWN_ERROR")
            )

        return data

    async def create_invoice(
            self,
            amount: float,
            expires_in: int,
            currency: str = getattr(EnvKeys, "PAY_CURRENCY", None) or "RUB",
            accepted_assets: str = "TON,USDT",
            payload: Optional[str] = None,
            description: Optional[str] = None,
            hidden_message: Optional[str] = None,
    ) -> dict:
        """
        Create a Crypto Pay invoice for given fiat amount/currency.
        """
        params = {
            "currency_type": "fiat",
            "fiat": currency,
            "amount": str(amount),
            "accepted_assets": accepted_assets,
            "expires_in": expires_in,
        }
        if payload:
            params["payload"] = payload
        if description:
            params["description"] = description
        if hidden_message:
            params["hidden_message"] = hidden_message

        response = await self._request("createInvoice", params)
        return response.get("result") or {}

    async def get_invoice(self, invoice_id: str) -> dict:
        """
        Fetch a single invoice by id.
        """
        params = {"invoice_ids": invoice_id}
        res = await self._request("getInvoices", params)
        items = res.get("result", {}).get("items")
        return items[0] if items else {}

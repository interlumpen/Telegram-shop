import json
import datetime
from decimal import Decimal, ROUND_HALF_UP

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery, SuccessfulPayment
from aiogram.fsm.context import FSMContext

from bot.database.methods import get_user_referral, buy_item_transaction, process_payment_with_referral
from bot.keyboards import back, payment_menu, close, get_payment_choice
from bot.logger_mesh import audit_logger, logger
from bot.misc import EnvKeys, ItemPurchaseRequest, validate_telegram_id, validate_money_amount, PaymentRequest, \
    sanitize_html
from bot.handlers.other import _any_payment_method_enabled, is_safe_item_name
from bot.misc.metrics import get_metrics
from bot.misc.payment import CryptoPayAPI, send_stars_invoice, send_fiat_invoice
from bot.filters import ValidAmountFilter
from bot.i18n import localize
from bot.states import BalanceStates

router = Router()


@router.callback_query(F.data == "replenish_balance")
async def replenish_balance_callback_handler(call: CallbackQuery, state: FSMContext):
    """Ask user for the amount if at least one payment method is enabled."""
    if not _any_payment_method_enabled():
        await call.answer(localize("payments.not_configured"), show_alert=True)
        return

    await call.message.edit_text(
        localize("payments.replenish_prompt", currency=EnvKeys.PAY_CURRENCY),
        reply_markup=back('profile')
    )
    await state.set_state(BalanceStates.waiting_amount)


@router.message(BalanceStates.waiting_amount, ValidAmountFilter())
async def replenish_balance_amount(message: Message, state: FSMContext):
    """Store amount and show payment methods."""
    try:
        # Validate amount using Pydantic
        amount = validate_money_amount(
            message.text,
            min_amount=Decimal(EnvKeys.MIN_AMOUNT),
            max_amount=Decimal(EnvKeys.MAX_AMOUNT)
        )

        await state.update_data(amount=int(amount))

        await message.answer(
            localize("payments.method_choose"),
            reply_markup=get_payment_choice()
        )
        await state.set_state(BalanceStates.waiting_payment)

    except ValueError as e:
        await message.answer(
            localize("payments.replenish_invalid",
                     min_amount=EnvKeys.MIN_AMOUNT,
                     max_amount=EnvKeys.MAX_AMOUNT,
                     currency=EnvKeys.PAY_CURRENCY),
            reply_markup=back('replenish_balance')
        )


@router.message(BalanceStates.waiting_amount)
async def invalid_amount(message: Message, state: FSMContext):
    """
    Tell user the amount is invalid.
    """
    await message.answer(
        localize("payments.replenish_invalid",
                 min_amount=EnvKeys.MIN_AMOUNT,
                 max_amount=EnvKeys.MAX_AMOUNT,
                 currency=EnvKeys.PAY_CURRENCY),
        reply_markup=back('replenish_balance')
    )


@router.callback_query(
    BalanceStates.waiting_payment,
    F.data.in_(["pay_cryptopay", "pay_stars", "pay_fiat"])
)
async def process_replenish_balance(call: CallbackQuery, state: FSMContext):
    """Create an invoice for the chosen payment method."""
    data = await state.get_data()
    amount = data.get('amount')

    if amount is None:
        await call.answer(localize("payments.session_expired"), show_alert=True)
        await call.message.edit_text(localize("menu.title"), reply_markup=back('back_to_menu'))
        await state.clear()
        return

    # Map callback data to provider
    provider_map = {
        "pay_cryptopay": "cryptopay",
        "pay_stars": "stars",
        "pay_fiat": "fiat"
    }
    provider = provider_map.get(call.data)

    try:
        # Validate payment request
        payment_request = PaymentRequest(
            amount=Decimal(amount),
            currency=EnvKeys.PAY_CURRENCY,
            provider=provider
        )

        amount_dec = payment_request.amount
        ttl_seconds = int(EnvKeys.PAYMENT_TIME)

        if call.data == "pay_cryptopay":
            if not EnvKeys.CRYPTO_PAY_TOKEN:
                await call.answer(localize("payments.not_configured"), show_alert=True)
                return

            try:
                crypto = CryptoPayAPI()
                invoice = await crypto.create_invoice(
                    amount=float(amount_dec),
                    currency=payment_request.currency,
                    accepted_assets="TON,USDT,BTC,ETH",
                    payload=str(call.from_user.id),
                    expires_in=ttl_seconds
                )
            except Exception as e:
                audit_logger.error(f"CryptoPay invoice creation failed: {e}")
                await call.answer(localize("payments.crypto.create_fail", error=str(e)), show_alert=True)
                return

            pay_url = invoice.get("mini_app_invoice_url")
            invoice_id = invoice.get("invoice_id")

            await state.update_data(invoice_id=invoice_id, payment_type="cryptopay")

            await call.message.edit_text(
                localize("payments.invoice.summary",
                         amount=int(amount_dec),
                         minutes=int(ttl_seconds / 60),
                         button=localize("btn.check_payment"),
                         currency=payment_request.currency),
                reply_markup=payment_menu(pay_url)
            )

        elif call.data == "pay_stars":
            if EnvKeys.STARS_PER_VALUE > 0:
                try:
                    await send_stars_invoice(
                        bot=call.message.bot,
                        chat_id=call.from_user.id,
                        amount=int(amount_dec),
                    )
                except Exception as e:
                    audit_logger.error(f"Stars invoice creation failed: {e}")
                    await call.answer(localize("payments.stars.create_fail", error=str(e)), show_alert=True)
                    return
                await state.clear()
            else:
                await call.answer(localize("payments.not_configured"), show_alert=True)
                return

        elif call.data == "pay_fiat":
            if not EnvKeys.TELEGRAM_PROVIDER_TOKEN:
                await call.answer(localize("payments.not_configured"), show_alert=True)
                return

            try:
                await send_fiat_invoice(
                    bot=call.message.bot,
                    chat_id=call.from_user.id,
                    amount=int(amount_dec),
                )
            except Exception as e:
                audit_logger.error(f"Fiat invoice creation failed: {e}")
                await call.answer(localize("payments.fiat.create_fail", error=str(e)), show_alert=True)
                return
            await state.clear()

    except Exception as e:
        logger.error(f"Payment processing error: {e}")
        await call.answer(localize("errors.something_wrong"), show_alert=True)


@router.callback_query(F.data == "check")
async def checking_payment(call: CallbackQuery, state: FSMContext):
    """
    Check CryptoPay invoice status and credit balance if paid.
    """
    user_id = call.from_user.id
    data = await state.get_data()
    payment_type = data.get("payment_type")

    if not payment_type:
        await call.answer(localize("payments.no_active_invoice"), show_alert=True)
        return

    if payment_type == "cryptopay":
        invoice_id = data.get("invoice_id")
        if not invoice_id:
            await call.answer(localize("payments.invoice_not_found"), show_alert=True)
            await state.clear()
            return

        try:
            crypto = CryptoPayAPI()
            info = await crypto.get_invoice(invoice_id)
        except Exception as e:
            await call.answer(localize("payments.crypto.create_fail", error=str(e)), show_alert=True)
            return

        status = info.get("status")
        if status == "paid":
            balance_amount = int(Decimal(str(info.get("amount", "0"))).quantize(Decimal("1.")))

            # Use transactional payment processing
            used_transaction_version = False

            success, error_msg = process_payment_with_referral(
                user_id=user_id,
                amount=Decimal(balance_amount),
                provider="cryptopay",
                external_id=str(invoice_id),
                referral_percent=EnvKeys.REFERRAL_PERCENT
            )

            used_transaction_version = True

            if not success:
                if error_msg == "already_processed":
                    await call.answer(localize("payments.already_processed"), show_alert=True)
                else:
                    await call.answer(localize("errors.general_error", e=error_msg), show_alert=True)
                return

            # Send a notification to the referrer
            referral_id = get_user_referral(user_id)
            if referral_id and EnvKeys.REFERRAL_PERCENT and used_transaction_version:
                try:
                    referral_amount = int(
                        Decimal(EnvKeys.REFERRAL_PERCENT) / Decimal(100) * Decimal(balance_amount)
                    )
                    if referral_amount > 0:
                        await call.bot.send_message(
                            referral_id,
                            localize('payments.referral.bonus',
                                     amount=referral_amount,
                                     name=call.from_user.first_name,
                                     id=call.from_user.id,
                                     currency=EnvKeys.PAY_CURRENCY),
                            reply_markup=close()
                        )
                except Exception:
                    pass

            await call.message.edit_text(
                localize("payments.topped_simple",
                         amount=balance_amount,
                         currency=EnvKeys.PAY_CURRENCY),
                reply_markup=back('profile')
            )
            await state.clear()

            # Audit log
            try:
                user_info = await call.bot.get_chat(user_id)
                audit_logger.info(
                    f"user {user_id} ({user_info.first_name}) "
                    f"replenished the balance by: {balance_amount} {EnvKeys.PAY_CURRENCY} (cryptopay)"
                )
            except Exception:
                pass

        elif status == "active":
            await call.answer(localize("payments.not_paid_yet"))
        else:
            await call.answer(localize("payments.expired"), show_alert=True)


@router.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    """Telegram requires answering ok=True before payment proceeds."""
    try:
        payload = json.loads(query.invoice_payload or "{}")
    except Exception:
        payload = {}
    amount = int(payload.get("amount", 0))
    if amount > 0:
        pass
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """
    Handle successful payment:
    - XTR (Stars): total_amount is ⭐. take CURRENCY from payload (amount) or convert ⭐ → CURRENCY.
    - Fiat: total_amount is minor units; divide by 100 (or 1 for JPY/KRW).
    """
    sp: SuccessfulPayment = message.successful_payment
    user_id = message.from_user.id

    payload = {}
    try:
        if sp.invoice_payload:
            payload = json.loads(sp.invoice_payload)
    except Exception:
        payload = {}

    amount = 0

    if sp.currency == "XTR":
        # Stars
        if "amount" in payload:
            amount = int(payload["amount"])
        else:
            amount = int(
                (Decimal(int(sp.total_amount)) / Decimal(str(EnvKeys.STARS_PER_VALUE)))
                .to_integral_value(rounding=ROUND_HALF_UP)
            )
    else:
        # Fiat
        currency = sp.currency.upper()
        multiplier = 1 if currency in {"JPY", "KRW"} else 100
        amount = int(Decimal(sp.total_amount) / Decimal(multiplier))

    if amount <= 0:
        await message.answer(localize("payments.unable_determine_amount"), reply_markup=close())
        return

    # Idempotence
    provider = "telegram" if sp.currency != "XTR" else "stars"
    external_id = sp.telegram_payment_charge_id or sp.provider_payment_charge_id or f"{provider}:{user_id}:{sp.total_amount}:{datetime.datetime.now().timestamp()}"

    success, error_msg = process_payment_with_referral(
        user_id=user_id,
        amount=Decimal(amount),
        provider=provider,
        external_id=external_id,
        referral_percent=EnvKeys.REFERRAL_PERCENT
    )

    if not success:
        if error_msg == "already_processed":
            await message.answer(localize("payments.already_processed"), reply_markup=close())
        else:
            await message.answer(localize("payments.processing_error"), reply_markup=close())
        return

    # Sending notification to referrer
    referral_id = get_user_referral(user_id)
    if referral_id and EnvKeys.REFERRAL_PERCENT:
        try:
            referral_operation = int(
                Decimal(EnvKeys.REFERRAL_PERCENT) / Decimal(100) * Decimal(amount)
            )
            if referral_operation > 0:
                await message.bot.send_message(
                    referral_id,
                    localize('payments.referral.bonus',
                             amount=referral_operation,
                             currency=EnvKeys.PAY_CURRENCY,
                             name=message.from_user.first_name,
                             id=message.from_user.id),
                    reply_markup=close()
                )
        except Exception:
            pass

    suffix = localize("payments.success_suffix.stars") if sp.currency == "XTR" else localize(
        "payments.success_suffix.tg")
    await message.answer(
        localize('payments.topped_with_suffix', amount=amount, suffix=suffix, currency=EnvKeys.PAY_CURRENCY),
        reply_markup=back('profile')
    )

    # audit log
    try:
        user_info = await message.bot.get_chat(user_id)
        audit_logger.info(
            f"user {user_id} ({user_info.first_name}) "
            f"replenished the balance by: {amount} {EnvKeys.PAY_CURRENCY} ({suffix})"
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith('buy_'))
async def buy_item_callback_handler(call: CallbackQuery):
    """Processing the purchase of goods with full transactional security."""
    try:
        metrics = get_metrics()
        if metrics:
            # Tracking the purchase funnel
            metrics.track_conversion("purchase_funnel", "view_item", call.from_user.id)

        # Extract and validate the product name
        raw_item_name = call.data[4:]

        # Validation via Pydantic
        purchase_request = ItemPurchaseRequest(
            item_name=raw_item_name,
            user_id=call.from_user.id
        )

        # Additional check for SQL injection
        if not is_safe_item_name(purchase_request.item_name):
            await call.answer(
                localize("errors.invalid_item_name"),
                show_alert=True
            )
            audit_logger.warning(
                f"Suspicious item name attempt from user {call.from_user.id}: {raw_item_name}"
            )
            return

        # User_id validation
        try:
            user_id = validate_telegram_id(call.from_user.id)
        except ValueError as e:
            await call.answer(localize("errors.invalid_user"), show_alert=True)
            return

        # Show the processing indicator
        await call.answer(localize("shop.purchase.processing"))

        # Execute a transactional purchase
        success, message, purchase_data = buy_item_transaction(
            user_id,
            purchase_request.item_name
        )

        if not success:
            # Error handling
            error_messages = {
                "user_not_found": "shop.purchase.fail.user_not_found",
                "item_not_found": "shop.item.not_found",
                "insufficient_funds": "shop.insufficient_funds",
                "out_of_stock": "shop.out_of_stock"
            }

            error_text = localize(
                error_messages.get(message, "shop.purchase.fail.general"),
                message=message
            )

            await call.message.edit_text(
                error_text,
                reply_markup=back(f'item_{purchase_request.item_name}')
            )

            if message not in error_messages:
                audit_logger.error(
                    f"Purchase error for user {user_id}, "
                    f"item {purchase_request.item_name}: {message}"
                )
            return

        # Successful purchase - sanitize the output

        if metrics:
            metrics.track_event("purchase", call.from_user.id, {
                "item": purchase_request.item_name,
                "price": purchase_data['price']
            })
            metrics.track_conversion("purchase_funnel", "purchase", call.from_user.id)

        safe_value = sanitize_html(purchase_data['value'])

        await call.message.edit_text(
            localize(
                'shop.purchase.success',
                balance=purchase_data['new_balance'],
                value=safe_value,
                currency=EnvKeys.PAY_CURRENCY
            ),
            parse_mode='HTML',
            reply_markup=back(f'item_{purchase_request.item_name}')
        )

        # Secure logging
        try:
            user_info = await call.bot.get_chat(user_id)
            audit_logger.info(
                f"User {user_id} ({user_info.first_name[:50]}) "
                f"bought item: {purchase_request.item_name[:100]} "
                f"for {purchase_data['price']} {EnvKeys.PAY_CURRENCY} "
                f"(unique_id: {purchase_data['unique_id']})"
            )
        except Exception as e:
            audit_logger.error(f"Failed to log purchase: {e}")

    except Exception as e:
        logger.error(f"Critical error in purchase handler: {e}")
        await call.answer(
            localize("errors.something_wrong"),
            show_alert=True
        )

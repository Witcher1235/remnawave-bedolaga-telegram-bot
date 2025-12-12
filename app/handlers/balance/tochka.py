import logging

from aiogram import types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import User
from app.keyboards.inline import get_back_keyboard
from app.localization.texts import get_texts
from app.services.payment_service import PaymentService
from app.states import BalanceStates
from app.utils.decorators import error_handler

logger = logging.getLogger(__name__)


@error_handler
async def start_tochka_payment(
    callback: types.CallbackQuery,
    db_user: User,
    state: FSMContext,
):
    texts = get_texts(db_user.language)

    if not settings.is_tochka_enabled():
        await callback.answer("❌ Оплата через Точку недоступна", show_alert=True)
        return

    message_text = texts.t(
        "TOCHKA_TOPUP_PROMPT",
        (
            "🏦 <b>Оплата через банк Точка</b>\n\n"
            "Введите сумму пополнения в рублях."
        ),
    )

    keyboard = get_back_keyboard(db_user.language)
    await callback.message.edit_text(
        message_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(BalanceStates.waiting_for_amount)
    await state.update_data(payment_method="tochka")
    await callback.answer()


@error_handler
async def process_tochka_payment_amount(
    message: types.Message,
    db_user: User,
    db: AsyncSession,
    amount_kopeks: int,
    state: FSMContext,
):
    texts = get_texts(db_user.language)

    if not settings.is_tochka_enabled():
        await message.answer("❌ Оплата через Точку недоступна")
        return

    payment_service = PaymentService(message.bot)

    description = texts.t("TOPUP_DESCRIPTION", "Пополнение баланса")
    result = await payment_service.create_tochka_payment(
        db,
        user_id=db_user.id,
        amount_kopeks=amount_kopeks,
        description=description,
        language=db_user.language,
    )

    if not result:
        await message.answer(texts.t("TOCHKA_PAYMENT_ERROR", "Не удалось создать платёж"))
        return

    checkout_url = result.get("checkout_url")
    status = result.get("status", "pending")
    await state.clear()

    response_text = texts.t(
        "TOCHKA_PAYMENT_CREATED",
        (
            "✅ Счёт создан.\n\n"
            "Статус: {status}\n"
            "Оплатите по ссылке: {link}"
        ),
    ).format(status=status, link=checkout_url or "—")

    await message.answer(response_text, disable_web_page_preview=False)

from __future__ import annotations

import logging
from datetime import datetime
from importlib import import_module
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import PaymentMethod, TransactionType
from app.external.tochka import TochkaClient
from app.utils.user_utils import format_referrer_info

logger = logging.getLogger(__name__)


class TochkaPaymentMixin:
    """Логика интеграции с платёжным шлюзом Точка."""

    _SUCCESS_STATUSES = {"succeeded", "paid", "completed"}
    _FAILED_STATUSES = {"failed", "canceled", "declined"}

    async def create_tochka_payment(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        amount_kopeks: int,
        description: str,
        language: str,
    ) -> Optional[Dict[str, Any]]:
        service: Optional[TochkaClient] = getattr(self, "tochka_client", None)
        if not service or not service.is_configured:
            logger.error("Tochka клиент не настроен")
            return None

        amount = round(amount_kopeks / 100, 2)
        try:
            response = await service.create_payment(
                amount=amount,
                currency=settings.TOCHKA_CURRENCY,
                description=description,
                return_url=settings.get_tochka_return_url(),
            )
        except Exception as error:  # pragma: no cover - network errors
            logger.exception("Ошибка Tochka при создании платежа: %s", error)
            return None

        if not response:
            logger.error("Tochka вернула пустой ответ")
            return None

        payment_id = str(response.get("id") or response.get("paymentId") or "").strip()
        checkout_url = response.get("redirectUrl") or response.get("paymentUrl")
        status = str(response.get("status") or "pending").lower()

        if not payment_id:
            logger.error("Tochka не вернула идентификатор платежа")
            return None

        metadata = {"language": language, "raw_response": response}

        payment_module = import_module("app.services.payment_service")
        payment = await payment_module.create_tochka_payment(
            db,
            user_id=user_id,
            payment_id=payment_id,
            amount_kopeks=amount_kopeks,
            currency=settings.TOCHKA_CURRENCY,
            description=description,
            status=status,
            checkout_url=checkout_url,
            metadata=metadata,
        )

        logger.info(
            "Создан Tochka платёж %s для пользователя %s", payment_id, user_id
        )

        return {
            "payment_id": payment.payment_id,
            "checkout_url": checkout_url,
            "status": payment.status,
            "local_payment_id": payment.id,
        }

    async def process_tochka_webhook(
        self, db: AsyncSession, payload: Dict[str, Any]
    ) -> bool:
        payment_module = import_module("app.services.payment_service")

        payment_id = str(payload.get("id") or payload.get("paymentId") or "").strip()
        if not payment_id:
            logger.error("Tochka webhook без id платежа")
            return False

        payment = await payment_module.get_tochka_payment_by_payment_id(db, payment_id)
        if not payment:
            logger.warning("Tochka webhook: платёж %s не найден", payment_id)
            return False

        raw_status = str(payload.get("status") or "").lower()
        if not raw_status:
            logger.warning("Tochka webhook: статус не указан для платежа %s", payment_id)
            return False

        update_kwargs = {
            "status": raw_status,
            "callback_payload": payload,
        }

        if raw_status in self._SUCCESS_STATUSES:
            paid_at = datetime.utcnow()
            await payment_module.update_tochka_payment(
                db,
                payment=payment,
                **update_kwargs,
                is_paid=True,
                paid_at=paid_at,
            )
            await self._finalize_tochka_payment(db, payment)
            return True

        if raw_status in self._FAILED_STATUSES:
            await payment_module.update_tochka_payment(
                db,
                payment=payment,
                **update_kwargs,
                is_paid=False,
            )
            logger.info("Tochka платёж %s отклонён", payment_id)
            return True

        await payment_module.update_tochka_payment(db, payment=payment, **update_kwargs)
        return True

    async def _finalize_tochka_payment(self, db: AsyncSession, payment: Any) -> Any:
        payment_module = import_module("app.services.payment_service")

        if payment.transaction_id:
            return payment

        user = await payment_module.get_user_by_id(db, payment.user_id)
        if not user:
            logger.error("Пользователь %s не найден для Tochka", payment.user_id)
            return payment

        transaction = await payment_module.create_transaction(
            db,
            user_id=payment.user_id,
            type=TransactionType.DEPOSIT,
            amount_kopeks=payment.amount_kopeks,
            description=f"Пополнение через Tochka ({payment.payment_id})",
            payment_method=PaymentMethod.TOCHKA,
            external_id=payment.payment_id,
            is_completed=True,
        )

        await payment_module.link_tochka_payment_to_transaction(
            db, payment=payment, transaction_id=transaction.id
        )

        old_balance = user.balance_kopeks
        was_first_topup = not user.has_made_first_topup

        user.balance_kopeks += payment.amount_kopeks
        user.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(user)

        referrer_info = format_referrer_info(user)

        try:
            from app.services.referral_service import process_referral_topup

            await process_referral_topup(
                db, user.id, payment.amount_kopeks, getattr(self, "bot", None)
            )
        except Exception as error:  # pragma: no cover - referral side effects
            logger.error("Ошибка реферального начисления Tochka: %s", error)

        if was_first_topup and not user.has_made_first_topup:
            user.has_made_first_topup = True
            await db.commit()
            await db.refresh(user)

        if getattr(self, "bot", None):
            try:
                from app.services.admin_notification_service import AdminNotificationService

                notification_service = AdminNotificationService(self.bot)
                await notification_service.send_balance_topup_notification(
                    user,
                    transaction,
                    old_balance,
                    topup_status="🟣 Tochka",
                    referrer_info=referrer_info,
                    subscription=getattr(user, "subscription", None),
                    promo_group=user.get_primary_promo_group(),
                    db=db,
                )
            except Exception as error:  # pragma: no cover - notify layer
                logger.error("Ошибка уведомления админов о платежe Tochka: %s", error)

        await self._send_payment_success_notification(
            user.telegram_id,
            payment.amount_kopeks,
            user,
            db=db,
            payment_method_title="Tochka",
        )

        return payment

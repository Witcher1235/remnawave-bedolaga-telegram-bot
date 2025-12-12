import logging
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import TochkaPayment

logger = logging.getLogger(__name__)


async def create_tochka_payment(
    db: AsyncSession,
    *,
    user_id: int,
    payment_id: str,
    amount_kopeks: int,
    currency: str,
    description: Optional[str],
    status: str,
    checkout_url: Optional[str],
    metadata: Optional[dict[str, Any]] = None,
) -> TochkaPayment:
    payment = TochkaPayment(
        user_id=user_id,
        payment_id=payment_id,
        amount_kopeks=amount_kopeks,
        currency=currency,
        description=description,
        status=status,
        checkout_url=checkout_url,
        metadata_json=metadata or {},
    )

    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    logger.info(
        "Создан Tochka платёж %s на сумму %s копеек для пользователя %s",
        payment_id,
        amount_kopeks,
        user_id,
    )

    return payment


async def get_tochka_payment_by_payment_id(
    db: AsyncSession, payment_id: str
) -> Optional[TochkaPayment]:
    result = await db.execute(
        select(TochkaPayment).where(TochkaPayment.payment_id == payment_id)
    )
    return result.scalar_one_or_none()


async def get_tochka_payment_by_id(
    db: AsyncSession, payment_id: int
) -> Optional[TochkaPayment]:
    result = await db.execute(select(TochkaPayment).where(TochkaPayment.id == payment_id))
    return result.scalar_one_or_none()


async def update_tochka_payment(
    db: AsyncSession,
    *,
    payment: TochkaPayment,
    status: Optional[str] = None,
    is_paid: Optional[bool] = None,
    paid_at: Optional[datetime] = None,
    checkout_url: Optional[str] = None,
    callback_payload: Optional[dict[str, Any]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> TochkaPayment:
    if status is not None:
        payment.status = status
    if is_paid is not None:
        payment.is_paid = is_paid
    if paid_at is not None:
        payment.paid_at = paid_at
    if checkout_url is not None:
        payment.checkout_url = checkout_url
    if callback_payload is not None:
        payment.callback_payload = callback_payload
    if metadata is not None:
        payment.metadata_json = metadata

    payment.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(payment)
    return payment


async def link_tochka_payment_to_transaction(
    db: AsyncSession, *, payment: TochkaPayment, transaction_id: int
) -> TochkaPayment:
    payment.transaction_id = transaction_id
    payment.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(payment)
    return payment

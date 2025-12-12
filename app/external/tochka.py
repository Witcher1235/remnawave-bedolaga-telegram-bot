from __future__ import annotations

import hmac
import hashlib
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class TochkaClient:
    """Простая обёртка над API банка Точка."""

    def __init__(self) -> None:
        self.base_url = (settings.TOCHKA_BASE_URL or "https://enter.tochka.com/api").rstrip("/")
        self.token = settings.TOCHKA_API_TOKEN
        self.webhook_secret = settings.TOCHKA_WEBHOOK_SECRET or ""
        self.timeout = aiohttp.ClientTimeout(total=30)

    @property
    def is_configured(self) -> bool:
        return bool(settings.TOCHKA_ENABLED and self.token)

    async def create_payment(
        self,
        *,
        amount: float,
        currency: str,
        description: Optional[str] = None,
        return_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "amount": round(amount, 2),
            "currency": currency,
        }
        if description:
            payload["description"] = description
        if return_url:
            payload["returnUrl"] = return_url

        return await self._request("POST", "/payments", json_data=payload)

    async def get_payment_status(self, payment_id: str) -> Optional[Dict[str, Any]]:
        endpoint = f"/payments/{payment_id}"
        return await self._request("GET", endpoint)

    def verify_webhook_signature(self, raw_body: bytes, signature: str | None) -> bool:
        if not signature or not self.webhook_secret:
            logger.error("Отсутствует подпись Tochka webhook")
            return False

        expected = hmac.new(
            self.webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature.strip())

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            logger.error("Tochka client is not configured")
            return None

        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(method, url, json=json_data, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        logger.error("Ошибка Tochka API %s: %s", response.status, text)
                        return None

                    if not text:
                        return None

                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        logger.error("Некорректный JSON ответ Tochka: %s", text)
                        return None
        except Exception as error:  # pragma: no cover - network layer
            logger.exception("Ошибка запроса Tochka API: %s", error)
            return None

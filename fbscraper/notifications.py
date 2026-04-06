"""Notification stubs for deal alerts (email, webhook)."""

import json
import logging
from typing import Optional

from .models import DealScore, DealQuality

logger = logging.getLogger(__name__)


class NotificationService:
    """Base class for deal notifications."""

    def __init__(self, min_quality: DealQuality = DealQuality.GOOD):
        self.min_quality = min_quality
        self._quality_rank = {
            DealQuality.EXCELLENT: 4,
            DealQuality.GOOD: 3,
            DealQuality.FAIR: 2,
            DealQuality.POOR: 1,
        }

    def should_notify(self, score: DealScore) -> bool:
        return self._quality_rank[score.quality] >= self._quality_rank[self.min_quality]

    def notify(self, scores: list[DealScore]) -> int:
        """Send notifications for qualifying deals. Returns count sent."""
        qualifying = [s for s in scores if self.should_notify(s)]
        if not qualifying:
            return 0
        return self._send(qualifying)

    def _send(self, scores: list[DealScore]) -> int:
        raise NotImplementedError


class EmailNotifier(NotificationService):
    """Email notification stub. Configure with SMTP or Resend API."""

    def __init__(self, recipient: str = "", min_quality: DealQuality = DealQuality.GOOD):
        super().__init__(min_quality)
        self.recipient = recipient

    def _send(self, scores: list[DealScore]) -> int:
        if not self.recipient:
            logger.info("Email notifications not configured (no recipient)")
            return 0

        # TODO: Implement with smtplib or Resend API
        subject = f"[FB Car Deals] {len(scores)} deals found!"
        body_lines = [f"Found {len(scores)} qualifying car deals:\n"]
        for score in scores[:10]:  # Top 10
            body_lines.append(f"  {score.summary_line()}")

        logger.info("Would send email to %s: %s (%d deals)", self.recipient, subject, len(scores))
        return len(scores)


class WebhookNotifier(NotificationService):
    """Webhook notification stub. POST deal data to a URL."""

    def __init__(self, webhook_url: str = "", min_quality: DealQuality = DealQuality.GOOD):
        super().__init__(min_quality)
        self.webhook_url = webhook_url

    def _send(self, scores: list[DealScore]) -> int:
        if not self.webhook_url:
            logger.info("Webhook notifications not configured (no URL)")
            return 0

        payload = {
            "event": "deals_found",
            "count": len(scores),
            "deals": [score.to_dict() for score in scores[:20]],
        }

        # TODO: Implement with requests or urllib
        logger.info("Would POST %d deals to %s", len(scores), self.webhook_url)
        return len(scores)

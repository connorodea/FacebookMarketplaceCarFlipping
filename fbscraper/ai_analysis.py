"""AI-powered deal analysis using Claude API."""

import json
import logging
import os
from typing import Optional

from .models import CarListing, DealScore, DealQuality, MarketEstimate

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = bool(ANTHROPIC_API_KEY)
except ImportError:
    ANTHROPIC_AVAILABLE = False


def is_ai_available() -> bool:
    return ANTHROPIC_AVAILABLE


class DealAnalyzer:
    """Uses Claude to provide intelligent deal analysis."""

    def __init__(self):
        if ANTHROPIC_AVAILABLE:
            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        else:
            self._client = None

    def analyze_deal(self, score: DealScore) -> dict:
        """Analyze a single deal and return AI insights."""
        if not self._client:
            return self._fallback_analysis(score)

        listing = score.listing
        market = score.market_estimate

        prompt = f"""You are a used car market expert helping a car flipper evaluate deals on Facebook Marketplace.

Analyze this listing and give a concise, actionable assessment:

**Listing:**
- {listing.year} {listing.make} {listing.model}
- Asking Price: ${listing.price:,}
- Mileage: {f'{listing.mileage:,} miles' if listing.mileage else 'Unknown'}
- Location: {listing.location}

**Market Data:**
- Trade-in Value: ${market.trade_in:,}
- Private Party Value: ${market.private_party:,}
- Dealer Retail Value: ${market.dealer_retail:,}
- Deal Ratio: {score.ratio:.2f} ({score.quality.value})
- Estimated Profit if Flipped: ${score.potential_profit:,}

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "verdict": "BUY" or "PASS" or "NEGOTIATE",
  "confidence": 1-10,
  "summary": "One sentence overall assessment",
  "flip_potential": "One sentence on resale profit potential",
  "risks": ["risk 1", "risk 2"],
  "negotiation_tip": "Specific price to offer and why",
  "estimated_flip_price": number,
  "estimated_flip_profit": number,
  "market_insight": "One sentence about this model's market position"
}}"""

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Parse JSON from response
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            result["ai_powered"] = True
            return result
        except json.JSONDecodeError:
            logger.warning("Failed to parse AI response as JSON")
            return self._fallback_analysis(score)
        except Exception as e:
            logger.warning("AI analysis failed: %s", e)
            return self._fallback_analysis(score)

    def analyze_batch(self, scores: list[DealScore], top_n: int = 5) -> dict:
        """Analyze a batch of deals and provide market summary."""
        if not self._client:
            return self._fallback_batch_analysis(scores)

        top_deals = scores[:top_n]
        deals_text = ""
        for i, s in enumerate(top_deals, 1):
            l = s.listing
            profit_str = f"+${s.potential_profit:,}" if s.potential_profit > 0 else f"-${abs(s.potential_profit):,}"
            deals_text += f"{i}. {l.year} {l.make} {l.model} - ${l.price:,} (Market: ${s.market_estimate.private_party:,}, Profit: {profit_str}, Ratio: {s.ratio:.2f})\n"

        total = len(scores)
        excellent = sum(1 for s in scores if s.quality == DealQuality.EXCELLENT)
        good = sum(1 for s in scores if s.quality == DealQuality.GOOD)
        avg_ratio = sum(s.ratio for s in scores) / total if total else 0

        prompt = f"""You are a used car market analyst. Analyze this batch of {total} Facebook Marketplace listings.

**Summary Stats:**
- Total listings: {total}
- Excellent deals: {excellent}
- Good deals: {good}
- Average deal ratio: {avg_ratio:.2f}

**Top {top_n} deals:**
{deals_text}

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "market_summary": "2-3 sentence market analysis",
  "top_pick": "Which deal to pursue first and why (1 sentence)",
  "strategy": "Overall buying strategy recommendation (1-2 sentences)",
  "market_trend": "hot" or "cold" or "neutral",
  "best_value_segment": "Which type of car offers best value right now",
  "avoid": "What to avoid in this market (1 sentence)"
}}"""

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result = json.loads(text)
            result["ai_powered"] = True
            return result
        except Exception as e:
            logger.warning("AI batch analysis failed: %s", e)
            return self._fallback_batch_analysis(scores)

    def generate_seller_message(self, score: DealScore) -> dict:
        """Generate 3 seller message templates for reaching out about a deal."""
        listing = score.listing
        market = score.market_estimate

        if self._client:
            prompt = f"""You are helping a car flipper write short messages to Facebook Marketplace sellers.

Generate 3 different buyer messages for this listing:
- {listing.year} {listing.make} {listing.model}
- Listed at ${listing.price:,}
- {f'{listing.mileage:,} miles' if listing.mileage else 'Unknown mileage'}

Message types:
1. "Eager buyer" — friendly, shows genuine interest, asks to see the car today/soon
2. "Value negotiator" — references market data to justify a lower offer (market value ~${market.private_party:,})
3. "Quick cash" — emphasizes cash in hand and fast closing

Each message should be 2-3 sentences max. Sound natural, not robotic.

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "messages": [
    {{"type": "eager", "text": "..."}},
    {{"type": "negotiator", "text": "..."}},
    {{"type": "cash", "text": "..."}}
  ]
}}"""

            try:
                response = self._client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                result = json.loads(text)
                result["ai_powered"] = True
                return result
            except Exception as e:
                logger.warning("AI message generation failed: %s", e)

        # Fallback: rule-based templates
        car = f"{listing.year} {listing.make} {listing.model}"
        offer_price = int(listing.price * 0.85)

        return {
            "messages": [
                {
                    "type": "eager",
                    "text": (
                        f"Hi! I'm really interested in your {car}. "
                        f"Is it still available? I'd love to come see it today if possible."
                    ),
                },
                {
                    "type": "negotiator",
                    "text": (
                        f"Hi, I'm interested in the {car}. "
                        f"Based on market comps I'm seeing similar vehicles around ${market.private_party:,}. "
                        f"Would you consider ${offer_price:,}?"
                    ),
                },
                {
                    "type": "cash",
                    "text": (
                        f"Hi, I'm a cash buyer looking at your {car}. "
                        f"I can bring ${offer_price:,} cash and pick it up today if the price works for you."
                    ),
                },
            ],
            "ai_powered": False,
        }

    def _fallback_analysis(self, score: DealScore) -> dict:
        """Rule-based analysis when AI is unavailable."""
        listing = score.listing
        market = score.market_estimate

        if score.ratio >= 1.30:
            verdict = "BUY"
            confidence = 8
            summary = f"Strong deal - {listing.year} {listing.make} {listing.model} is priced well below market value."
        elif score.ratio >= 1.15:
            verdict = "BUY"
            confidence = 6
            summary = f"Good deal - {listing.year} {listing.make} {listing.model} is priced below market."
        elif score.ratio >= 0.95:
            verdict = "NEGOTIATE"
            confidence = 5
            summary = f"Fair price - try negotiating down 10-15% on this {listing.year} {listing.make} {listing.model}."
        else:
            verdict = "PASS"
            confidence = 7
            summary = f"Overpriced - {listing.year} {listing.make} {listing.model} is above market value."

        target_price = int(market.private_party * 0.75)
        flip_price = int(market.private_party * 0.95)
        flip_profit = flip_price - listing.price

        risks = []
        if listing.mileage and listing.mileage > 100000:
            risks.append("High mileage may limit buyer pool")
        if listing.age > 10:
            risks.append("Older vehicle may need costly repairs")
        if score.market_estimate.source == "category_fallback":
            risks.append("Market value is an estimate - verify with local comps")
        if not risks:
            risks.append("Standard used car risks apply")

        return {
            "verdict": verdict,
            "confidence": confidence,
            "summary": summary,
            "flip_potential": f"Could flip for ~${flip_price:,} (profit: ${flip_profit:,})" if flip_profit > 0 else "Limited flip potential at this price.",
            "risks": risks,
            "negotiation_tip": f"Offer ${target_price:,} - that's 75% of private party value.",
            "estimated_flip_price": flip_price,
            "estimated_flip_profit": max(0, flip_profit),
            "market_insight": f"{listing.make} {listing.model} holds value {'well' if listing.make in ('Toyota','Honda','Mazda','Subaru') else 'average'} in the used market.",
            "ai_powered": False,
        }

    def _fallback_batch_analysis(self, scores: list[DealScore]) -> dict:
        total = len(scores)
        excellent = sum(1 for s in scores if s.quality == DealQuality.EXCELLENT)
        avg_ratio = sum(s.ratio for s in scores) / total if total else 0

        if excellent > total * 0.2:
            trend = "hot"
            summary = f"Strong buyer's market - {excellent} excellent deals found out of {total} listings."
        elif excellent > 0:
            trend = "neutral"
            summary = f"Mixed market - {excellent} excellent deals found among {total} listings."
        else:
            trend = "cold"
            summary = f"Seller's market - no excellent deals found in {total} listings."

        top = scores[0] if scores else None
        top_pick = f"Best deal: {top.listing.year} {top.listing.make} {top.listing.model} at ${top.listing.price:,} (ratio {top.ratio:.2f})" if top else "No deals available."

        # Find best segment
        segments: dict[str, list[float]] = {}
        for s in scores:
            key = s.listing.make
            segments.setdefault(key, []).append(s.ratio)
        best_seg = max(segments.items(), key=lambda x: sum(x[1])/len(x[1]), default=("Unknown", [0]))

        return {
            "market_summary": summary,
            "top_pick": top_pick,
            "strategy": "Focus on vehicles with ratio above 1.2 for best flip margins. Negotiate aggressively on anything above 1.0.",
            "market_trend": trend,
            "best_value_segment": f"{best_seg[0]} models showing best value ratios",
            "avoid": "Skip anything with ratio below 0.9 unless you can negotiate significantly.",
            "ai_powered": False,
        }

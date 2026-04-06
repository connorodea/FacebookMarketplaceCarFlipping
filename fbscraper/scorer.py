"""Deal scoring engine that uses independent market values."""

import logging
from typing import Optional

from .models import CarListing, DealScore, DealQuality, FlipEstimate, MarketEstimate, MileageCondition
from .pricing import PricingEngine

logger = logging.getLogger(__name__)

# Condition factor applied to market value based on mileage
CONDITION_FACTORS = {
    MileageCondition.EXCELLENT: 1.05,
    MileageCondition.GOOD: 1.00,
    MileageCondition.FAIR: 0.92,
    MileageCondition.HIGH: 0.82,
    MileageCondition.VERY_HIGH: 0.70,
    MileageCondition.UNKNOWN: 0.92,
}


class DealScorer:
    """Scores car deals by comparing listing price to independent market values."""

    def __init__(self, pricing_engine: Optional[PricingEngine] = None):
        self.pricing = pricing_engine or PricingEngine()

    def score(self, listing: CarListing) -> DealScore:
        """Score a single car listing."""
        market_estimate = self.pricing.estimate(listing)
        condition = MileageCondition.from_mileage(listing.mileage)
        condition_factor = CONDITION_FACTORS[condition]

        # Adjusted market value based on mileage condition
        adjusted_pp = market_estimate.private_party * condition_factor

        # Ratio = market_value / listing_price (higher = better deal)
        ratio = adjusted_pp / listing.price if listing.price > 0 else 0.0

        # Determine deal quality
        if ratio >= 1.30:
            quality = DealQuality.EXCELLENT
        elif ratio >= 1.15:
            quality = DealQuality.GOOD
        elif ratio >= 0.95:
            quality = DealQuality.FAIR
        else:
            quality = DealQuality.POOR

        # Potential profit if bought at listing and sold at private party
        potential_profit = int(adjusted_pp - listing.price)

        # Flip estimate with realistic costs
        flip_estimate = self._estimate_flip(listing, market_estimate, condition)

        # Build notes
        notes_parts = []
        if market_estimate.source == "category_fallback":
            notes_parts.append("Market value from category estimate (no exact data)")
        if market_estimate.source == "fuzzy_match":
            notes_parts.append("Market value from fuzzy model match")
        if condition == MileageCondition.EXCELLENT:
            notes_parts.append("Low mileage bonus")
        if condition in (MileageCondition.HIGH, MileageCondition.VERY_HIGH):
            notes_parts.append("High mileage penalty applied")

        return DealScore(
            listing=listing,
            market_estimate=market_estimate,
            condition=condition,
            ratio=round(ratio, 3),
            quality=quality,
            potential_profit=potential_profit,
            flip_estimate=flip_estimate,
            notes="; ".join(notes_parts),
        )

    def _estimate_flip(self, listing: CarListing, market: MarketEstimate,
                       condition: MileageCondition) -> FlipEstimate:
        """Estimate realistic flip costs and net profit."""
        # Estimate repair costs based on condition and age
        age = listing.age
        if condition == MileageCondition.EXCELLENT:
            repair = int(listing.price * 0.03)  # 3% for detailing/minor fixes
        elif condition == MileageCondition.GOOD:
            repair = int(listing.price * 0.05)  # 5%
        elif condition == MileageCondition.FAIR:
            repair = int(listing.price * 0.08) + (200 if age > 8 else 0)
        elif condition in (MileageCondition.HIGH, MileageCondition.VERY_HIGH):
            repair = int(listing.price * 0.12) + 500
        else:
            repair = int(listing.price * 0.07)

        repair = max(150, min(repair, 3000))  # Clamp between $150-$3000

        # Sell at 95% of private party (realistic quick sale)
        sell_price = int(market.private_party * 0.95)

        return FlipEstimate(
            purchase_price=listing.price,
            estimated_repair=repair,
            detailing=200,
            listing_fees=50,
            transport=0,
            sell_price=sell_price,
        )

    def score_batch(self, listings: list[CarListing]) -> list[DealScore]:
        """Score a batch of listings, sorted by ratio (best deals first)."""
        scores = []
        for listing in listings:
            try:
                scores.append(self.score(listing))
            except Exception as e:
                logger.warning("Failed to score %s %s %s: %s",
                               listing.year, listing.make, listing.model, e)
                continue

        scores.sort(key=lambda s: s.ratio, reverse=True)
        return scores

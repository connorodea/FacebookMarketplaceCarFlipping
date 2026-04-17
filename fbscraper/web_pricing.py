"""Real-time market pricing via Claude API with web search.

Uses Claude's web search tool to look up current KBB, Edmunds, and NADA
values for any vehicle, replacing the static lookup table with live data.
"""

import json
import logging
import os
from typing import Optional

from .models import CarListing, MarketEstimate

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

try:
    import anthropic
    ANTHROPIC_AVAILABLE = bool(ANTHROPIC_API_KEY)
except ImportError:
    ANTHROPIC_AVAILABLE = False


class WebPricingEngine:
    """Fetches real-time market values using Claude with web search."""

    def __init__(self):
        if ANTHROPIC_AVAILABLE:
            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        else:
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def estimate(self, listing: CarListing) -> Optional[MarketEstimate]:
        """Look up real-time market value for a car listing."""
        return self.lookup(
            year=listing.year,
            make=listing.make,
            model=listing.model,
            mileage=listing.mileage,
        )

    def lookup(
        self,
        year: int,
        make: str,
        model: str,
        mileage: Optional[int] = None,
        trim: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> Optional[MarketEstimate]:
        """Look up real-time market value for a vehicle.

        Args:
            year: Model year
            make: Manufacturer (e.g. Toyota)
            model: Model name (e.g. Camry)
            mileage: Odometer reading
            trim: Trim level (e.g. SE, XLE)
            condition: Vehicle condition (excellent, good, fair, poor)

        Returns:
            MarketEstimate with trade-in, private party, and dealer retail values,
            or None if the lookup fails.
        """
        if not self._client:
            logger.warning("Claude API not available for web pricing lookup")
            return None

        car_desc = f"{year} {make} {model}"
        if trim:
            car_desc += f" {trim}"

        mileage_str = f" with {mileage:,} miles" if mileage else ""
        condition_str = f" in {condition} condition" if condition else ""

        prompt = f"""Look up the current market value of a {car_desc}{mileage_str}{condition_str}.

Search for KBB (Kelley Blue Book) values, Edmunds values, and any other reliable pricing sources you can find.

I need these three values:
1. **Trade-in value** - what a dealer would offer
2. **Private party value** - what a private seller would get
3. **Dealer retail value** - what a dealer would charge

Also note any important context about this vehicle's market position (reliability, demand, common issues).

Respond in this exact JSON format (no markdown, just raw JSON):
{{
  "trade_in": <integer dollar amount>,
  "private_party": <integer dollar amount>,
  "dealer_retail": <integer dollar amount>,
  "sources": ["source1", "source2"],
  "market_notes": "Brief notes about this vehicle's market position",
  "confidence": "high" or "medium" or "low",
  "kbb_range": {{"low": <int>, "high": <int>}},
  "edmunds_range": {{"low": <int>, "high": <int>}}
}}

If you cannot find exact values for a source, provide your best estimate based on what you found and note the confidence level accordingly. Always return the JSON."""

        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 5,
                    }
                ],
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text from response (may contain tool use blocks)
            text = self._extract_text(response)
            if not text:
                logger.warning("No text response from web pricing lookup")
                return None

            data = self._parse_json(text)
            if not data:
                logger.warning("Failed to parse web pricing response")
                return None

            # Build source description
            sources = data.get("sources", [])
            confidence = data.get("confidence", "medium")
            source_str = f"web_search ({', '.join(sources[:3])})" if sources else "web_search"
            if confidence != "high":
                source_str += f" [{confidence} confidence]"

            estimate = MarketEstimate(
                trade_in=int(data.get("trade_in", 0)),
                private_party=int(data.get("private_party", 0)),
                dealer_retail=int(data.get("dealer_retail", 0)),
                source=source_str,
            )

            # Attach extra metadata as attributes for display
            estimate._raw_data = data  # type: ignore[attr-defined]

            return estimate

        except Exception as e:
            error_msg = str(e)
            if "usage limits" in error_msg.lower() or "rate limit" in error_msg.lower():
                logger.error("API usage limit reached: %s", e)
                raise RuntimeError(
                    "Anthropic API usage limit reached. "
                    "Check your plan at console.anthropic.com or wait for the reset."
                ) from e
            logger.error("Web pricing lookup failed: %s", e)
            return None

    def _extract_text(self, response) -> str:
        """Extract the final text block from a response that may include tool use."""
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "\n".join(text_parts)

    def _parse_json(self, text: str) -> Optional[dict]:
        """Parse JSON from response text, handling markdown fences."""
        text = text.strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fence
        if "```" in text:
            parts = text.split("```")
            for part in parts[1::2]:  # odd-indexed parts are inside fences
                content = part.strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    continue

        # Try finding JSON object in text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

        return None

    def lookup_detailed(
        self,
        year: int,
        make: str,
        model: str,
        mileage: Optional[int] = None,
        trim: Optional[str] = None,
        condition: Optional[str] = None,
    ) -> Optional[dict]:
        """Like lookup() but returns the full raw data dict for detailed display."""
        if not self._client:
            return None

        estimate = self.lookup(year, make, model, mileage, trim, condition)
        if estimate and hasattr(estimate, "_raw_data"):
            result = estimate._raw_data  # type: ignore[attr-defined]
            result["trade_in"] = estimate.trade_in
            result["private_party"] = estimate.private_party
            result["dealer_retail"] = estimate.dealer_retail
            result["source"] = estimate.source
            return result
        return None

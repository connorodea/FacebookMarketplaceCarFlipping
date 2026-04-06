"""Market pricing engine using independent lookup data."""

import json
import logging
from pathlib import Path
from typing import Optional

from .models import CarListing, MarketEstimate

logger = logging.getLogger(__name__)

# Brand -> category mapping for fallback pricing
BRAND_CATEGORY = {
    "fiat": "economy", "smart": "economy", "mitsubishi": "economy",
    "suzuki": "economy", "scion": "economy", "geo": "economy",

    "ford": "standard", "chevrolet": "standard", "nissan": "standard",
    "hyundai": "standard", "kia": "standard", "volkswagen": "standard",
    "dodge": "standard", "chrysler": "standard", "pontiac": "standard",
    "saturn": "standard", "mercury": "standard", "oldsmobile": "standard",
    "plymouth": "standard",

    "toyota": "reliable", "honda": "reliable", "mazda": "reliable",
    "subaru": "reliable",

    "acura": "premium", "infiniti": "premium", "volvo": "premium",
    "genesis": "premium", "buick": "premium", "lincoln": "premium",

    "bmw": "luxury", "mercedes-benz": "luxury", "audi": "luxury",
    "lexus": "luxury", "cadillac": "luxury", "porsche": "luxury",
    "jaguar": "luxury", "maserati": "luxury", "tesla": "luxury",

    "jeep": "truck_suv", "ram": "truck_suv", "gmc": "truck_suv",
    "hummer": "truck_suv",
}

# Standard depreciation curve (percent of value retained per year)
DEPRECIATION_CURVE = {
    0: 1.00,
    1: 0.80,
    2: 0.68,
    3: 0.61,
    4: 0.55,
    5: 0.50,
    6: 0.46,
    7: 0.42,
    8: 0.39,
    9: 0.36,
    10: 0.33,
    12: 0.28,
    15: 0.22,
    20: 0.15,
    25: 0.10,
}


class PricingEngine:
    """Estimates market values using a curated lookup table with interpolation fallback."""

    def __init__(self, lookup_path: Optional[str] = None):
        if lookup_path is None:
            lookup_path = str(Path(__file__).parent.parent / "data" / "market_values.json")

        self._lookup: dict = {}
        self._categories: dict = {}
        self._load_data(lookup_path)

    def _load_data(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._categories = data.pop("_category_defaults", {})
            data.pop("_meta", None)
            self._lookup = data
            logger.info("Loaded market data: %d makes", len(self._lookup))
        except FileNotFoundError:
            logger.warning("Market values file not found at %s", path)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in market values file: %s", e)

    def estimate(self, listing: CarListing) -> MarketEstimate:
        """Estimate market value for a car listing.

        Priority:
        1. Exact make/model/year lookup
        2. Make/model with nearest-year interpolation
        3. Category-based depreciation fallback
        """
        make_lower = listing.make.lower()
        model_lower = listing.model.lower()

        # Try exact lookup
        result = self._exact_lookup(make_lower, model_lower, listing.year)
        if result:
            return result

        # Try interpolation from nearest years
        result = self._interpolated_lookup(make_lower, model_lower, listing.year)
        if result:
            return result

        # Try with model aliases (e.g., "3 series" vs "330i")
        result = self._fuzzy_model_lookup(make_lower, model_lower, listing.year)
        if result:
            return result

        # Category-based depreciation fallback
        return self._category_fallback(listing)

    def _exact_lookup(self, make: str, model: str, year: int) -> Optional[MarketEstimate]:
        if make in self._lookup and model in self._lookup[make]:
            year_data = self._lookup[make][model].get(str(year))
            if year_data:
                return MarketEstimate(
                    trade_in=year_data["ti"],
                    private_party=year_data["pp"],
                    dealer_retail=year_data["dr"],
                    source="exact_lookup",
                )
        return None

    def _interpolated_lookup(self, make: str, model: str, year: int) -> Optional[MarketEstimate]:
        if make not in self._lookup or model not in self._lookup[make]:
            return None

        year_map = self._lookup[make][model]
        available_years = sorted(int(y) for y in year_map.keys())

        if not available_years:
            return None

        # Find nearest years
        lower_year = None
        upper_year = None
        for y in available_years:
            if y <= year:
                lower_year = y
            if y >= year and upper_year is None:
                upper_year = y

        if lower_year is None and upper_year is None:
            return None

        # If we only have one bound, extrapolate from it
        if lower_year is None:
            ref = year_map[str(upper_year)]
            years_diff = upper_year - year
            decay = 0.93 ** years_diff  # ~7% per year for older cars
            return MarketEstimate(
                trade_in=int(ref["ti"] * decay),
                private_party=int(ref["pp"] * decay),
                dealer_retail=int(ref["dr"] * decay),
                source="interpolated",
            )

        if upper_year is None:
            ref = year_map[str(lower_year)]
            years_diff = year - lower_year
            growth = 1.04 ** years_diff  # ~4% per year for newer
            return MarketEstimate(
                trade_in=int(ref["ti"] * growth),
                private_party=int(ref["pp"] * growth),
                dealer_retail=int(ref["dr"] * growth),
                source="interpolated",
            )

        if lower_year == upper_year:
            ref = year_map[str(lower_year)]
            return MarketEstimate(
                trade_in=ref["ti"],
                private_party=ref["pp"],
                dealer_retail=ref["dr"],
                source="exact_lookup",
            )

        # Linear interpolation between two years
        lower_data = year_map[str(lower_year)]
        upper_data = year_map[str(upper_year)]
        span = upper_year - lower_year
        ratio = (year - lower_year) / span

        return MarketEstimate(
            trade_in=int(lower_data["ti"] + (upper_data["ti"] - lower_data["ti"]) * ratio),
            private_party=int(lower_data["pp"] + (upper_data["pp"] - lower_data["pp"]) * ratio),
            dealer_retail=int(lower_data["dr"] + (upper_data["dr"] - lower_data["dr"]) * ratio),
            source="interpolated",
        )

    def _fuzzy_model_lookup(self, make: str, model: str, year: int) -> Optional[MarketEstimate]:
        """Try to match model names that are substrings or common aliases."""
        if make not in self._lookup:
            return None

        models_available = self._lookup[make]
        model_clean = model.replace("-", "").replace(" ", "").lower()

        for known_model in models_available:
            known_clean = known_model.replace("-", "").replace(" ", "").lower()
            # Check if one contains the other (e.g., "civic" matches "civic si")
            if model_clean in known_clean or known_clean in model_clean:
                result = self._interpolated_lookup(make, known_model, year)
                if result:
                    result.source = "fuzzy_match"
                    return result

        return None

    def _category_fallback(self, listing: CarListing) -> MarketEstimate:
        """Estimate using category-based MSRP depreciation when no specific data exists."""
        make_lower = listing.make.lower()
        category = BRAND_CATEGORY.get(make_lower, "standard")
        cat_data = self._categories.get(category, self._categories.get("standard", {}))

        avg_msrp = cat_data.get("avg_msrp", 30000)
        retention = cat_data.get("retention_rate", 0.90)

        # Apply depreciation curve
        age = listing.age
        depreciation_factor = self._get_depreciation_factor(age, retention)
        estimated_pp = int(avg_msrp * depreciation_factor)

        # Ensure minimum value
        estimated_pp = max(estimated_pp, 1500)

        return MarketEstimate(
            trade_in=int(estimated_pp * 0.85),
            private_party=estimated_pp,
            dealer_retail=int(estimated_pp * 1.15),
            source="category_fallback",
        )

    def _get_depreciation_factor(self, age: int, retention_rate: float) -> float:
        """Get depreciation factor for a given age, adjusted by brand retention."""
        # Find bracketing years in the curve
        lower_age = 0
        upper_age = 25

        for curve_age in sorted(DEPRECIATION_CURVE.keys()):
            if curve_age <= age:
                lower_age = curve_age
            if curve_age >= age:
                upper_age = curve_age
                break

        lower_val = DEPRECIATION_CURVE[lower_age]
        upper_val = DEPRECIATION_CURVE[upper_age]

        if lower_age == upper_age:
            base_factor = lower_val
        else:
            ratio = (age - lower_age) / (upper_age - lower_age)
            base_factor = lower_val + (upper_val - lower_val) * ratio

        # Adjust by brand retention (1.0 = neutral, >1.0 = retains better)
        retention_adjustment = retention_rate / 0.90  # normalized to standard
        return base_factor * retention_adjustment

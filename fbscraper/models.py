"""Data models for the Facebook Marketplace Car Scraper."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional
import json
import re


class DealQuality(Enum):
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"


class MileageCondition(Enum):
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    HIGH = "High"
    VERY_HIGH = "Very High"
    UNKNOWN = "Unknown"

    @classmethod
    def from_mileage(cls, mileage: Optional[int]) -> "MileageCondition":
        if mileage is None:
            return cls.UNKNOWN
        if mileage < 50_000:
            return cls.EXCELLENT
        if mileage < 80_000:
            return cls.GOOD
        if mileage < 120_000:
            return cls.FAIR
        if mileage < 180_000:
            return cls.HIGH
        return cls.VERY_HIGH


@dataclass
class SearchConfig:
    location: str = "atlanta"
    search_term: str = ""
    min_price: int = 250
    max_price: int = 55000
    min_year: int = 1995
    max_year: int = 2025
    min_mileage: int = 0
    max_mileage: int = 200000
    scroll_count: int = 10
    max_listings: int = 500
    make: str = ""
    model: str = ""
    transmission: str = ""
    fuel_type: str = ""
    body_style: str = ""
    condition: str = ""
    seller_type: str = ""
    sort_by: str = "creation_time_descend"
    radius: int = 20

    def build_url(self) -> str:
        """Build Facebook Marketplace search URL."""
        if self.search_term.strip():
            base_url = f"https://www.facebook.com/marketplace/{self.location}/search?"
            params = [f"query={self.search_term.strip().replace(' ', '%20')}"]
        else:
            base_url = f"https://www.facebook.com/marketplace/{self.location}/vehicles?"
            params = []

        param_mapping = {
            "min_price": "minPrice",
            "max_price": "maxPrice",
            "min_mileage": "minMileage",
            "max_mileage": "maxMileage",
            "min_year": "minYear",
            "max_year": "maxYear",
            "radius": "radius",
        }

        for attr, url_param in param_mapping.items():
            value = getattr(self, attr)
            if value is not None:
                params.append(f"{url_param}={value}")

        filter_mapping = {
            "make": "make",
            "model": "model",
            "transmission": "transmission",
            "fuel_type": "fuel_type",
            "body_style": "body_style",
            "condition": "condition",
            "seller_type": "seller_type",
            "sort_by": "sortBy",
        }

        for attr, url_param in filter_mapping.items():
            value = getattr(self, attr)
            if value:
                params.append(f"{url_param}={value.lower().replace(' ', '_')}")

        params.append("exact=false")
        return base_url + "&".join(params)


@dataclass
class CarListing:
    price: int
    year: int
    make: str
    model: str
    mileage: Optional[int] = None
    location: str = "Unknown"
    url: str = ""
    listing_id: str = ""
    scraped_at: datetime = field(default_factory=datetime.now)
    raw_text: str = ""

    @property
    def age(self) -> int:
        return datetime.now().year - self.year

    @property
    def signature(self) -> str:
        """Unique signature for deduplication."""
        return f"{self.price}_{self.year}_{self.make}_{self.model}_{self.mileage}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["scraped_at"] = self.scraped_at.isoformat()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def extract_listing_id(url: str) -> str:
        """Extract the item ID from a Facebook Marketplace URL."""
        match = re.search(r"/marketplace/item/(\d+)", url)
        return match.group(1) if match else ""


@dataclass
class MarketEstimate:
    trade_in: int
    private_party: int
    dealer_retail: int
    source: str = "lookup_table"

    @property
    def average(self) -> float:
        return (self.trade_in + self.private_party + self.dealer_retail) / 3


@dataclass
class DealScore:
    listing: CarListing
    market_estimate: MarketEstimate
    condition: MileageCondition
    ratio: float
    quality: DealQuality
    potential_profit: int
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "ratio": round(self.ratio, 3),
            "quality": self.quality.value,
            "condition": self.condition.value,
            "potential_profit": self.potential_profit,
            "notes": self.notes,
            "listing": self.listing.to_dict(),
            "market_estimate": asdict(self.market_estimate),
        }

    def summary_line(self) -> str:
        """One-line summary for CLI display."""
        m = self.listing
        profit_str = f"+${self.potential_profit:,}" if self.potential_profit > 0 else f"-${abs(self.potential_profit):,}"
        return (
            f"{m.year} {m.make} {m.model} - ${m.price:,} "
            f"(Ratio: {self.ratio:.2f}, {self.quality.value}, {profit_str})"
        )

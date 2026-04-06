"""Parse Facebook Marketplace listing text into structured CarListing objects."""

import re
import logging
from datetime import datetime
from typing import Optional

from .models import CarListing

logger = logging.getLogger(__name__)

# Brand normalization map
BRAND_ALIASES = {
    "chevy": "Chevrolet",
    "vw": "Volkswagen",
    "mercedes": "Mercedes-Benz",
    "mercedes-benz": "Mercedes-Benz",
    "land": "Land Rover",
    "range": "Range Rover",
    "alfa": "Alfa Romeo",
}

# All recognized car brands (lowercase)
CAR_BRANDS = {
    "toyota", "honda", "ford", "chevrolet", "chevy", "nissan", "hyundai",
    "kia", "mazda", "subaru", "volkswagen", "vw", "bmw", "mercedes", "audi",
    "lexus", "acura", "infiniti", "volvo", "jaguar", "porsche", "ferrari",
    "lamborghini", "maserati", "bentley", "tesla", "lucid",
    "rivian", "cadillac", "lincoln", "buick", "gmc", "ram", "dodge",
    "chrysler", "jeep", "mitsubishi", "genesis", "alfa", "fiat", "mini",
    "land", "rover", "range", "saab", "pontiac", "saturn",
    "hummer", "scion", "isuzu", "suzuki", "smart", "mercury",
    "oldsmobile", "plymouth", "geo",
}

# Tokens that should NOT be treated as model names
NON_MODEL_TOKENS = {
    "$", "miles", "mi", "km", "k", "automatic", "manual", "awd", "fwd", "rwd",
    "4wd", "clean", "title", "salvage", "rebuilt", "obo", "firm", "or", "best",
    "offer", "no", "trades", "cash", "only", "runs", "drives", "great", "good",
    "needs", "work", "as", "is", "for", "sale", "by", "owner", "dealer",
}

# Mileage regex patterns ordered by specificity
MILEAGE_PATTERNS = [
    re.compile(r"(\d[\d,]*)\s*k\s*miles?", re.IGNORECASE),
    re.compile(r"(\d[\d,]*)\s*miles?", re.IGNORECASE),
    re.compile(r"(\d[\d,]*)\s*k\s*mi\b", re.IGNORECASE),
    re.compile(r"(\d[\d,]*)\s*mi\b", re.IGNORECASE),
    re.compile(r"(\d[\d,]*)\s*k\b", re.IGNORECASE),
]

# Location pattern: "City, ST" or "City Name, ST"
LOCATION_PATTERNS = [
    re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})"),
]


def normalize_brand(raw: str) -> str:
    """Normalize a brand name to its canonical form."""
    lower = raw.lower().replace("-", "").replace("_", "")
    if lower in BRAND_ALIASES:
        return BRAND_ALIASES[lower]
    return raw.title()


def parse_price(tokens: list[str]) -> Optional[int]:
    """Extract price from tokenized listing text."""
    for token in tokens:
        match = re.search(r"\$([0-9,]+)", token)
        if match:
            try:
                return int(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def parse_year(tokens: list[str]) -> Optional[int]:
    """Extract year from tokenized listing text."""
    current_year = datetime.now().year
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year = int(token)
            if 1980 <= year <= current_year + 1:
                return year
    return None


def parse_make_model(tokens: list[str]) -> tuple[Optional[str], Optional[str]]:
    """Extract make and model from tokenized listing text."""
    for i, token in enumerate(tokens):
        token_lower = token.lower().replace("-", "").replace("_", "")
        if token_lower in CAR_BRANDS:
            make = normalize_brand(token)

            # Try to extract model from next tokens
            model = None
            if i + 1 < len(tokens):
                next_token = tokens[i + 1]
                # Skip if next token looks like price, mileage, or noise
                if (not next_token.startswith("$")
                        and not next_token.isdigit()
                        and next_token.lower() not in NON_MODEL_TOKENS
                        and len(next_token) > 1):
                    model = next_token.title()

                    # Check for multi-word model (e.g., "Grand Cherokee")
                    if i + 2 < len(tokens):
                        extra = tokens[i + 2]
                        if (not extra.startswith("$")
                                and not extra.isdigit()
                                and extra.lower() not in NON_MODEL_TOKENS
                                and not re.match(r"^\d", extra)
                                and len(extra) > 1
                                and "," not in extra):
                            model += f" {extra.title()}"

            return make, model

    return None, None


def parse_mileage(text: str) -> Optional[int]:
    """Extract mileage from listing text."""
    for pattern in MILEAGE_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_num = match.group(1).replace(",", "")
            try:
                mileage = int(raw_num)
                # If "k" is in the matched string and value < 1000, multiply
                matched_text = match.group(0).lower()
                if "k" in matched_text and mileage < 1000:
                    mileage *= 1000
                # Sanity check: mileage should be between 0 and 500k
                if 0 <= mileage <= 500_000:
                    return mileage
            except ValueError:
                continue
    return None


def parse_location(text: str) -> str:
    """Extract location (City, ST) from listing text."""
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return "Unknown"


def parse_listing_text(text: str, url: str = "") -> Optional[CarListing]:
    """Parse a Facebook Marketplace listing text block into a CarListing.

    Returns None if essential fields (price, year, make) cannot be extracted.
    """
    tokens = text.split()

    price = parse_price(tokens)
    year = parse_year(tokens)
    make, model = parse_make_model(tokens)

    if price is None or year is None or make is None:
        return None

    mileage = parse_mileage(text)
    location = parse_location(text)
    listing_id = CarListing.extract_listing_id(url)

    return CarListing(
        price=price,
        year=year,
        make=make,
        model=model or "Unknown",
        mileage=mileage,
        location=location,
        url=url,
        listing_id=listing_id,
        raw_text=text[:500],  # Keep first 500 chars for debugging
    )

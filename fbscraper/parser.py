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
    "mercedesbenz": "Mercedes-Benz",
    "land": "Land Rover",
    "range": "Range Rover",
    "alfa": "Alfa Romeo",
}

# Brands that should stay UPPERCASE
UPPERCASE_BRANDS = {"bmw", "gmc", "ram"}

# Known model patterns by brand (for fuzzy matching to lookup table)
BRAND_MODEL_NORMALIZE = {
    "bmw": {
        r"3\d{2}[id]?": "3 Series",
        r"5\d{2}[id]?": "5 Series",
        r"7\d{2}[id]?": "7 Series",
        r"x[1-7]": "X{}",  # X3, X5, etc. - handled specially
        r"m[2-8]": "M{}",
    },
    "mercedes-benz": {
        r"c\s*\d{3}": "C-Class",
        r"e\s*\d{3}": "E-Class",
        r"s\s*\d{3}": "S-Class",
        r"gl[a-z]*\s*\d{3}": "GLC",
    },
    "lexus": {
        r"[eirn]s\s*\d{3}": lambda m: m.group(0)[:2].upper(),
        r"[eirn]x\s*\d{3}": lambda m: m.group(0)[:2].upper(),
        r"rx": "RX",
        r"es": "ES",
        r"is": "IS",
        r"nx": "NX",
    },
    "infiniti": {
        r"q\s*[35][05]": lambda m: m.group(0).upper().replace(" ", ""),
        r"qx\s*\d{2}": lambda m: m.group(0).upper().replace(" ", ""),
    },
    "acura": {
        r"tl[xs]?": "TLX",
        r"ilx": "ILX",
        r"mdx": "MDX",
        r"rdx": "RDX",
    },
}

# All recognized car brands (lowercase)
CAR_BRANDS = {
    "toyota", "honda", "ford", "chevrolet", "chevy", "nissan", "hyundai",
    "kia", "mazda", "subaru", "volkswagen", "vw", "bmw", "mercedes", "audi",
    "lexus", "acura", "infiniti", "volvo", "jaguar", "porsche", "ferrari",
    "mercedes-benz", "mercedesbenz",
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
    if lower in UPPERCASE_BRANDS:
        return lower.upper()
    return raw.title()


def normalize_model(make: str, raw_model: str) -> str:
    """Normalize model name using brand-specific patterns.

    E.g., BMW "328i" -> "3 Series", Mercedes "C300" -> "C-Class".
    """
    if not raw_model or raw_model == "Unknown":
        return raw_model

    make_lower = make.lower()
    if make_lower not in BRAND_MODEL_NORMALIZE:
        return raw_model

    combined = raw_model.lower().strip()
    patterns = BRAND_MODEL_NORMALIZE[make_lower]

    for pattern, replacement in patterns.items():
        match = re.match(pattern, combined, re.IGNORECASE)
        if match:
            if callable(replacement):
                return replacement(match)
            if "{}" in replacement:
                # Extract the digit, e.g., "X3" -> "X3"
                digit = re.search(r"\d", combined)
                if digit:
                    return replacement.replace("{}", digit.group())
            return replacement

    return raw_model


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
                # Allow alphanumeric models like "328i", "X5", "Q50", "CR-V", "F-150"
                is_valid_model = (
                    not next_token.startswith("$")
                    and next_token.lower() not in NON_MODEL_TOKENS
                    and len(next_token) > 1
                    # Allow pure digits only for known patterns (e.g., BMW "328")
                    and (not next_token.isdigit() or make.upper() in ("BMW", "FIAT", "MINI"))
                    # Filter out mileage-like tokens (e.g., "78k", "120k", "45000")
                    and not re.match(r"^\d+[kK]$", next_token)
                    and not re.match(r"^\d{4,}$", next_token)  # 5+ digit numbers are likely mileage
                )
                if is_valid_model:
                    model = next_token.title()

                    # Check for multi-word model (e.g., "Grand Cherokee")
                    if i + 2 < len(tokens):
                        extra = tokens[i + 2]
                        if (not extra.startswith("$")
                                and not extra.isdigit()
                                and extra.lower() not in NON_MODEL_TOKENS
                                and len(extra) > 1
                                and "," not in extra
                                and not re.match(r"^\d+[kK]$", extra)
                                and not re.match(r"^\d{4,}$", extra)):
                            model += f" {extra.title()}"

            # Normalize model to match lookup table names
            if model:
                model = normalize_model(make, model)

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

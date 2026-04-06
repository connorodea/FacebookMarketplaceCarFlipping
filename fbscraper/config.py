"""Configuration management for the Facebook Marketplace Car Scraper."""

import csv
import logging
from pathlib import Path
from typing import Union

from .models import SearchConfig

logger = logging.getLogger(__name__)

# Mapping from Preferences.csv keys to SearchConfig field names
_CSV_KEY_MAP = {
    "Minimum Mileage": "min_mileage",
    "Maximum Mileage": "max_mileage",
    "Minimum Price": "min_price",
    "Maximum Price": "max_price",
    "Minimum Year": "min_year",
    "Maximum Year": "max_year",
    "Scroll Down Length": "scroll_count",
    "Search Term": "search_term",
    "Location": "location",
    "Make": "make",
    "Model": "model",
    "Transmission": "transmission",
    "Fuel Type": "fuel_type",
    "Body Style": "body_style",
    "Condition": "condition",
    "Seller Type": "seller_type",
    "Sort By": "sort_by",
    "Radius": "radius",
}

# Integer fields in SearchConfig
_INT_FIELDS = {
    "min_mileage", "max_mileage", "min_price", "max_price",
    "min_year", "max_year", "scroll_count", "max_listings", "radius",
}


def load_config(preferences_file: str = "Preferences.csv") -> SearchConfig:
    """Load SearchConfig from a Preferences.csv file.

    Backward-compatible with the original 7-field format and the
    extended 18-field format.
    """
    path = Path(preferences_file)
    if not path.exists():
        logger.warning("Preferences file '%s' not found, using defaults", preferences_file)
        return SearchConfig()

    raw: dict[str, Union[str, int]] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=",")
            for row in reader:
                if len(row) >= 2:
                    raw[row[0].strip()] = row[1].strip()
    except Exception as e:
        logger.error("Error reading preferences file: %s. Using defaults.", e)
        return SearchConfig()

    # Map CSV keys to SearchConfig fields
    kwargs: dict[str, Union[str, int]] = {}
    for csv_key, field_name in _CSV_KEY_MAP.items():
        if csv_key in raw and raw[csv_key]:
            value = raw[csv_key]
            if field_name in _INT_FIELDS:
                try:
                    kwargs[field_name] = int(value)
                except ValueError:
                    logger.warning("Invalid integer for '%s': '%s', skipping", csv_key, value)
            else:
                kwargs[field_name] = value

    config = SearchConfig(**kwargs)
    logger.info("Loaded config: location=%s, price=%d-%d, year=%d-%d",
                config.location, config.min_price, config.max_price,
                config.min_year, config.max_year)
    return config


def save_config(config: SearchConfig, preferences_file: str = "Preferences.csv") -> None:
    """Save SearchConfig back to Preferences.csv (backward-compatible format)."""
    # Reverse mapping: field_name -> csv_key
    field_to_csv = {v: k for k, v in _CSV_KEY_MAP.items()}

    rows = []
    for field_name, csv_key in sorted(field_to_csv.items(), key=lambda x: x[1]):
        value = getattr(config, field_name, "")
        rows.append([csv_key, str(value) if value else ""])

    path = Path(preferences_file)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    logger.info("Saved config to %s", preferences_file)

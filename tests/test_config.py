"""Tests for configuration loading and URL building."""

import pytest
import tempfile
import os
from fbscraper.config import load_config, save_config
from fbscraper.models import SearchConfig


class TestLoadConfig:
    def test_load_existing_preferences(self):
        """Should load the actual Preferences.csv from the project root."""
        config = load_config("Preferences.csv")
        assert config.location == "atlanta"
        assert config.min_price == 250
        assert config.max_price == 55000
        assert config.min_year == 1995
        assert config.max_year == 2020
        assert config.scroll_count == 10

    def test_defaults_on_missing_file(self):
        config = load_config("nonexistent_file.csv")
        assert config.location == "atlanta"
        assert config.min_price == 250

    def test_save_and_reload(self):
        config = SearchConfig(location="miami", min_price=5000, max_price=30000)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = f.name

        try:
            save_config(config, path)
            loaded = load_config(path)
            assert loaded.location == "miami"
            assert loaded.min_price == 5000
            assert loaded.max_price == 30000
        finally:
            os.unlink(path)


class TestURLBuilding:
    def test_basic_url(self):
        config = SearchConfig(
            location="atlanta",
            min_price=250,
            max_price=55000,
            min_year=1995,
            max_year=2020,
        )
        url = config.build_url()
        assert "facebook.com/marketplace/atlanta/vehicles?" in url
        assert "minPrice=250" in url
        assert "maxPrice=55000" in url
        assert "minYear=1995" in url
        assert "maxYear=2020" in url
        assert "exact=false" in url

    def test_search_term_url(self):
        config = SearchConfig(location="miami", search_term="Honda Civic")
        url = config.build_url()
        assert "facebook.com/marketplace/miami/search?" in url
        assert "query=Honda%20Civic" in url

    def test_filters_in_url(self):
        config = SearchConfig(
            location="atlanta",
            make="Toyota",
            transmission="automatic",
            sort_by="price_ascend",
        )
        url = config.build_url()
        assert "make=toyota" in url
        assert "transmission=automatic" in url
        assert "sortBy=price_ascend" in url

    def test_backward_compatible_with_original(self):
        """The URL format should match what the original scraper produced."""
        config = load_config("Preferences.csv")
        url = config.build_url()
        # Must include these params which the original build_facebook_url produced
        assert "minPrice=" in url
        assert "maxPrice=" in url
        assert "minMileage=" in url
        assert "maxMileage=" in url
        assert "exact=false" in url

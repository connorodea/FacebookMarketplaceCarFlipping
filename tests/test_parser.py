"""Tests for the listing text parser."""

import pytest
from fbscraper.parser import (
    parse_listing_text,
    parse_price,
    parse_year,
    parse_make_model,
    parse_mileage,
    parse_location,
    normalize_brand,
)


class TestParsePrice:
    def test_basic_price(self):
        assert parse_price(["$14,500"]) == 14500

    def test_no_comma(self):
        assert parse_price(["$5400"]) == 5400

    def test_large_price(self):
        assert parse_price(["$125,000"]) == 125000

    def test_price_in_text(self):
        assert parse_price(["2015", "Honda", "Civic", "$14,500"]) == 14500

    def test_no_price(self):
        assert parse_price(["2015", "Honda", "Civic"]) is None


class TestParseYear:
    def test_basic_year(self):
        assert parse_year(["2015"]) == 2015

    def test_year_in_context(self):
        assert parse_year(["$14,500", "2015", "Honda", "Civic"]) == 2015

    def test_old_year(self):
        assert parse_year(["1995"]) == 1995

    def test_too_old(self):
        assert parse_year(["1970"]) is None

    def test_not_a_year(self):
        assert parse_year(["14500"]) is None

    def test_no_year(self):
        assert parse_year(["Honda", "Civic"]) is None


class TestParseMakeModel:
    def test_basic(self):
        make, model = parse_make_model(["2015", "Honda", "Civic"])
        assert make == "Honda"
        assert model == "Civic"

    def test_chevy_normalize(self):
        make, model = parse_make_model(["2018", "Chevy", "Malibu"])
        assert make == "Chevrolet"
        assert model == "Malibu"

    def test_vw_normalize(self):
        make, model = parse_make_model(["2020", "VW", "Jetta"])
        assert make == "Volkswagen"

    def test_mercedes_normalize(self):
        make, model = parse_make_model(["2019", "Mercedes", "C300"])
        assert make == "Mercedes-Benz"

    def test_no_model(self):
        make, model = parse_make_model(["Honda", "$5000"])
        assert make == "Honda"
        assert model is None  # $5000 is filtered out

    def test_known_brand_rivian(self):
        make, model = parse_make_model(["2020", "Rivian", "R1T"])
        assert make == "Rivian"
        assert model == "R1T"

    def test_multi_word_model_not_bleeding(self):
        """Model shouldn't bleed into location-like tokens."""
        make, model = parse_make_model(["2015", "Honda", "Civic", "$14,500"])
        assert make == "Honda"
        assert model == "Civic"  # Should NOT include "$14,500"


class TestParseMileage:
    def test_k_miles(self):
        assert parse_mileage("78k miles") == 78000

    def test_plain_miles(self):
        assert parse_mileage("112000 miles") == 112000

    def test_comma_miles(self):
        assert parse_mileage("112,000 miles") == 112000

    def test_k_shorthand(self):
        assert parse_mileage("45k") == 45000

    def test_no_mileage(self):
        assert parse_mileage("2015 Honda Civic $14500") is None


class TestParseLocation:
    def test_city_state(self):
        assert parse_location("Listed in Atlanta, GA") == "Atlanta, GA"

    def test_multi_word_city(self):
        assert parse_location("Sandy Springs, GA") == "Sandy Springs, GA"

    def test_no_location(self):
        assert parse_location("2015 Honda Civic") == "Unknown"


class TestNormalizeBrand:
    def test_chevy(self):
        assert normalize_brand("chevy") == "Chevrolet"

    def test_vw(self):
        assert normalize_brand("vw") == "Volkswagen"

    def test_mercedes(self):
        assert normalize_brand("mercedes") == "Mercedes-Benz"

    def test_normal_brand(self):
        assert normalize_brand("honda") == "Honda"

    def test_title_case(self):
        assert normalize_brand("TOYOTA") == "Toyota"


class TestParseListingText:
    def test_full_listing(self):
        text = "$14,500 2015 Honda Civic 78k miles Atlanta, GA"
        url = "https://www.facebook.com/marketplace/item/1234567890/"
        listing = parse_listing_text(text, url)

        assert listing is not None
        assert listing.price == 14500
        assert listing.year == 2015
        assert listing.make == "Honda"
        assert listing.model == "Civic"
        assert listing.mileage == 78000
        assert listing.location == "Atlanta, GA"
        assert listing.listing_id == "1234567890"

    def test_missing_price_returns_none(self):
        assert parse_listing_text("2015 Honda Civic") is None

    def test_missing_year_returns_none(self):
        assert parse_listing_text("$14,500 Honda Civic") is None

    def test_missing_make_returns_none(self):
        assert parse_listing_text("$14,500 2015 Unknown-brand Sedan") is None

    def test_missing_model_defaults_to_unknown(self):
        text = "$14,500 2015 Honda"
        listing = parse_listing_text(text)
        assert listing is not None
        assert listing.model == "Unknown"

    def test_extract_listing_id_from_url(self):
        from fbscraper.models import CarListing
        assert CarListing.extract_listing_id("https://www.facebook.com/marketplace/item/1567237611082758/") == "1567237611082758"
        assert CarListing.extract_listing_id("https://example.com/foo") == ""

"""Tests for the market pricing engine."""

import pytest
from fbscraper.pricing import PricingEngine
from fbscraper.models import CarListing


@pytest.fixture
def engine():
    return PricingEngine()


class TestExactLookup:
    def test_known_car(self, engine):
        listing = CarListing(price=10000, year=2015, make="Honda", model="Civic")
        est = engine.estimate(listing)
        assert est.source == "exact_lookup"
        assert est.private_party > 0
        assert est.trade_in < est.private_party < est.dealer_retail

    def test_toyota_camry_2020(self, engine):
        listing = CarListing(price=15000, year=2020, make="Toyota", model="Camry")
        est = engine.estimate(listing)
        assert est.source == "exact_lookup"
        # 2020 Camry should be worth ~$21k private party
        assert 18000 <= est.private_party <= 25000

    def test_case_insensitive(self, engine):
        listing = CarListing(price=10000, year=2018, make="HONDA", model="civic")
        est = engine.estimate(listing)
        assert est.private_party > 0


class TestInterpolation:
    def test_missing_year_interpolates(self, engine):
        # 2011 Corolla not in data, but 2010 and 2012 are
        listing = CarListing(price=10000, year=2011, make="Toyota", model="Corolla")
        est = engine.estimate(listing)
        assert est.source == "interpolated"
        assert est.private_party > 0

    def test_older_year_extrapolates(self, engine):
        listing = CarListing(price=3000, year=1998, make="Toyota", model="Camry")
        est = engine.estimate(listing)
        assert est.private_party > 0


class TestFuzzyMatch:
    def test_partial_model_name(self, engine):
        # "Civic Si" should match "Civic"
        listing = CarListing(price=15000, year=2018, make="Honda", model="Civic Si")
        est = engine.estimate(listing)
        assert est.source in ("exact_lookup", "fuzzy_match", "interpolated")
        assert est.private_party > 0


class TestCategoryFallback:
    def test_unknown_model(self, engine):
        listing = CarListing(price=10000, year=2018, make="Honda", model="Ridgeline")
        est = engine.estimate(listing)
        # Ridgeline not in our data, should fall back to category
        assert est.private_party > 0

    def test_unknown_make(self, engine):
        listing = CarListing(price=5000, year=2015, make="Saab", model="9-3")
        est = engine.estimate(listing)
        assert est.source == "category_fallback"
        assert est.private_party > 0

    def test_values_are_reasonable(self, engine):
        """Category fallback should produce reasonable values, not absurd ones."""
        listing = CarListing(price=10000, year=2015, make="UnknownMake", model="X")
        est = engine.estimate(listing)
        assert 1500 <= est.private_party <= 50000

    def test_trade_in_less_than_private_party(self, engine):
        listing = CarListing(price=10000, year=2015, make="UnknownMake", model="X")
        est = engine.estimate(listing)
        assert est.trade_in < est.private_party

    def test_dealer_more_than_private_party(self, engine):
        listing = CarListing(price=10000, year=2015, make="UnknownMake", model="X")
        est = engine.estimate(listing)
        assert est.dealer_retail > est.private_party


class TestPricingIndependence:
    """The critical test: market value must be independent of listing price."""

    def test_same_car_different_prices(self, engine):
        """Two identical cars with different listing prices should get the same market value."""
        car_cheap = CarListing(price=5000, year=2015, make="Honda", model="Civic")
        car_expensive = CarListing(price=20000, year=2015, make="Honda", model="Civic")

        est_cheap = engine.estimate(car_cheap)
        est_expensive = engine.estimate(car_expensive)

        # Market values should be identical - they're the SAME CAR
        assert est_cheap.private_party == est_expensive.private_party
        assert est_cheap.trade_in == est_expensive.trade_in
        assert est_cheap.dealer_retail == est_expensive.dealer_retail

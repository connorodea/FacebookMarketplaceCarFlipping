"""Tests for the deal scoring engine."""

import pytest
from fbscraper.scorer import DealScorer
from fbscraper.models import CarListing, DealQuality, MileageCondition


@pytest.fixture
def scorer():
    return DealScorer()


class TestDealScoring:
    def test_underpriced_car_scores_well(self, scorer):
        """A car priced well below market should score Excellent."""
        listing = CarListing(price=8000, year=2018, make="Honda", model="Civic", mileage=60000)
        score = scorer.score(listing)
        # 2018 Civic market ~$17k, listing at $8k = great deal
        assert score.ratio > 1.5
        assert score.quality == DealQuality.EXCELLENT
        assert score.potential_profit > 5000

    def test_overpriced_car_scores_poorly(self, scorer):
        """A car priced above market should score Poor."""
        listing = CarListing(price=25000, year=2015, make="Honda", model="Civic", mileage=100000)
        score = scorer.score(listing)
        assert score.ratio < 0.95
        assert score.quality == DealQuality.POOR
        assert score.potential_profit < 0

    def test_fair_priced_car(self, scorer):
        """A car at roughly market value should be Fair."""
        listing = CarListing(price=13000, year=2015, make="Honda", model="Civic", mileage=78000)
        score = scorer.score(listing)
        assert 0.85 <= score.ratio <= 1.20

    def test_mileage_affects_score(self, scorer):
        """Higher mileage should reduce the score."""
        low_miles = CarListing(price=15000, year=2018, make="Honda", model="Civic", mileage=30000)
        high_miles = CarListing(price=15000, year=2018, make="Honda", model="Civic", mileage=150000)

        score_low = scorer.score(low_miles)
        score_high = scorer.score(high_miles)

        assert score_low.ratio > score_high.ratio
        assert score_low.potential_profit > score_high.potential_profit

    def test_unknown_mileage(self, scorer):
        listing = CarListing(price=12000, year=2016, make="Toyota", model="Camry")
        score = scorer.score(listing)
        assert score.condition == MileageCondition.UNKNOWN
        assert score.ratio > 0


class TestBatchScoring:
    def test_batch_sorted_by_ratio(self, scorer, sample_listings):
        scores = scorer.score_batch(sample_listings)
        ratios = [s.ratio for s in scores]
        assert ratios == sorted(ratios, reverse=True)

    def test_batch_handles_empty(self, scorer):
        assert scorer.score_batch([]) == []

    def test_batch_skips_errors(self, scorer):
        """Bad data shouldn't crash the batch."""
        listings = [
            CarListing(price=0, year=2020, make="Honda", model="Civic"),  # price=0
            CarListing(price=10000, year=2018, make="Toyota", model="Camry"),
        ]
        scores = scorer.score_batch(listings)
        # Should still get at least one result
        assert len(scores) >= 1


class TestMileageCondition:
    def test_excellent(self):
        assert MileageCondition.from_mileage(30000) == MileageCondition.EXCELLENT

    def test_good(self):
        assert MileageCondition.from_mileage(65000) == MileageCondition.GOOD

    def test_fair(self):
        assert MileageCondition.from_mileage(100000) == MileageCondition.FAIR

    def test_high(self):
        assert MileageCondition.from_mileage(150000) == MileageCondition.HIGH

    def test_very_high(self):
        assert MileageCondition.from_mileage(200000) == MileageCondition.VERY_HIGH

    def test_unknown(self):
        assert MileageCondition.from_mileage(None) == MileageCondition.UNKNOWN

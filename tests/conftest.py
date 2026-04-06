"""Shared test fixtures based on real scraped data."""

import pytest
from datetime import datetime
from fbscraper.models import CarListing, SearchConfig, MarketEstimate, DealScore, DealQuality, MileageCondition


@pytest.fixture
def sample_listings() -> list[CarListing]:
    """Real listings based on actual scraped data from Oct 2025."""
    return [
        CarListing(price=12500, year=2018, make="Acura", model="Ilx", mileage=54000,
                   location="Atlanta, GA", url="https://www.facebook.com/marketplace/item/1567237611082758/"),
        CarListing(price=16000, year=2018, make="Infiniti", model="Q50", mileage=57000,
                   location="Stockbridge, GA", url="https://www.facebook.com/marketplace/item/1234567890/"),
        CarListing(price=5400, year=2016, make="Ford", model="Fusion", mileage=119000,
                   location="Norcross, GA", url="https://www.facebook.com/marketplace/item/9876543210/"),
        CarListing(price=14500, year=2015, make="Honda", model="Civic", mileage=78000,
                   location="Atlanta, GA", url="https://www.facebook.com/marketplace/item/1111111111/"),
        CarListing(price=9200, year=2012, make="Toyota", model="Corolla", mileage=112000,
                   location="Decatur, GA", url="https://www.facebook.com/marketplace/item/2222222222/"),
        CarListing(price=19800, year=2017, make="Nissan", model="Altima", mileage=62000,
                   location="Sandy Springs, GA", url="https://www.facebook.com/marketplace/item/3333333333/"),
        CarListing(price=13200, year=2014, make="Chevrolet", model="Malibu", mileage=89000,
                   location="Marietta, GA", url="https://www.facebook.com/marketplace/item/4444444444/"),
        CarListing(price=21500, year=2018, make="Ford", model="Fusion", mileage=45000,
                   location="Roswell, GA", url="https://www.facebook.com/marketplace/item/5555555555/"),
    ]


@pytest.fixture
def sample_config() -> SearchConfig:
    return SearchConfig(
        location="atlanta",
        min_price=250,
        max_price=55000,
        min_year=1995,
        max_year=2020,
        max_mileage=200000,
        scroll_count=10,
    )


@pytest.fixture
def honda_civic_2015() -> CarListing:
    return CarListing(
        price=14500, year=2015, make="Honda", model="Civic",
        mileage=78000, location="Atlanta, GA",
    )


@pytest.fixture
def cheap_ford_fusion() -> CarListing:
    return CarListing(
        price=5400, year=2016, make="Ford", model="Fusion",
        mileage=119000, location="Norcross, GA",
    )

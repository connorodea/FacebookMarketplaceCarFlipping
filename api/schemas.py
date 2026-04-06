"""Pydantic schemas for API request/response models."""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class DealQualityEnum(str, Enum):
    EXCELLENT = "Excellent"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"


class SearchRequest(BaseModel):
    location: str = Field(default="atlanta", description="City for marketplace search")
    search_term: str = Field(default="", description="Search keywords")
    min_price: int = Field(default=250, ge=0)
    max_price: int = Field(default=55000, ge=0)
    min_year: int = Field(default=1995, ge=1980)
    max_year: int = Field(default=2025, le=2027)
    max_mileage: int = Field(default=200000, ge=0)
    make: str = Field(default="", description="Car make filter")
    model: str = Field(default="", description="Car model filter")
    scroll_count: int = Field(default=10, ge=1, le=50)


class ListingResponse(BaseModel):
    price: int
    year: int
    make: str
    model: str
    mileage: Optional[int] = None
    location: str = "Unknown"
    url: str = ""


class MarketEstimateResponse(BaseModel):
    trade_in: int
    private_party: int
    dealer_retail: int
    source: str


class FlipEstimateResponse(BaseModel):
    purchase_price: int = 0
    estimated_repair: int = 0
    detailing: int = 0
    listing_fees: int = 0
    transport: int = 0
    total_cost: int = 0
    sell_price: int = 0
    net_profit: int = 0
    roi_percent: float = 0.0


class DealResponse(BaseModel):
    ratio: float
    quality: str
    condition: str
    potential_profit: int
    notes: str
    listing: ListingResponse
    market_estimate: MarketEstimateResponse
    flip_estimate: Optional[FlipEstimateResponse] = None


class SearchRunResponse(BaseModel):
    id: int
    timestamp: str
    location: str
    search_term: str
    listing_count: int


class SearchResultResponse(BaseModel):
    run_id: int
    total_deals: int
    excellent_count: int
    good_count: int
    fair_count: int
    poor_count: int
    deals: list[DealResponse]


class QuickScoreRequest(BaseModel):
    """Score a single car without scraping."""
    price: int = Field(ge=1, description="Listing price")
    year: int = Field(ge=1980, le=2027)
    make: str
    model: str
    mileage: Optional[int] = Field(default=None, ge=0)


class StatsResponse(BaseModel):
    total_listings: int
    total_runs: int
    avg_deal_ratio: float
    best_deal_ratio: float
    top_makes: list[dict]
    recent_excellent_deals: list[DealResponse]

"""Tests for the FastAPI web application."""

import pytest
from fastapi.testclient import TestClient

from api.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStatus:
    def test_status_endpoint(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        assert "playwright_available" in data
        assert "session_active" in data

    def test_dashboard_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "DealFinder" in response.text


class TestQuickScore:
    def test_score_known_car(self, client):
        response = client.post("/api/score", json={
            "price": 8000,
            "year": 2018,
            "make": "Honda",
            "model": "Civic",
            "mileage": 60000,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["quality"] == "Excellent"
        assert data["ratio"] > 1.5
        assert data["potential_profit"] > 5000
        assert data["listing"]["price"] == 8000
        assert data["market_estimate"]["private_party"] > 0

    def test_score_overpriced_car(self, client):
        response = client.post("/api/score", json={
            "price": 25000,
            "year": 2015,
            "make": "Honda",
            "model": "Civic",
            "mileage": 100000,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["quality"] == "Poor"
        assert data["potential_profit"] < 0

    def test_score_without_mileage(self, client):
        response = client.post("/api/score", json={
            "price": 12000,
            "year": 2017,
            "make": "Toyota",
            "model": "Camry",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["condition"] == "Unknown"

    def test_score_validation_error(self, client):
        response = client.post("/api/score", json={
            "price": -1,
            "year": 2020,
            "make": "Honda",
            "model": "Civic",
        })
        assert response.status_code == 422

    def test_score_independence(self, client):
        """Same car at different prices should get same market value."""
        cheap = client.post("/api/score", json={
            "price": 5000, "year": 2018, "make": "Honda", "model": "Civic",
        }).json()
        expensive = client.post("/api/score", json={
            "price": 25000, "year": 2018, "make": "Honda", "model": "Civic",
        }).json()

        assert cheap["market_estimate"]["private_party"] == expensive["market_estimate"]["private_party"]
        assert cheap["ratio"] > expensive["ratio"]


class TestHistory:
    def test_history_empty(self, client):
        response = client.get("/api/history")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_history_invalid_run(self, client):
        response = client.get("/api/history/99999")
        assert response.status_code == 404


class TestStats:
    def test_stats_endpoint(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_listings" in data
        assert "total_runs" in data
        assert "avg_deal_ratio" in data


class TestSearchListings:
    def test_search_no_filters(self, client):
        response = client.get("/api/search/listings")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "listings" in data

    def test_search_with_make_filter(self, client):
        response = client.get("/api/search/listings?make=Honda")
        assert response.status_code == 200

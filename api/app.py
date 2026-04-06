"""FastAPI application for the Facebook Marketplace Car Scraper."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from fbscraper.config import load_config
from fbscraper.models import CarListing, SearchConfig, DealQuality
from fbscraper.pricing import PricingEngine
from fbscraper.scorer import DealScorer
from fbscraper.scraper import FacebookScraper, has_valid_session, is_playwright_available
from fbscraper.storage import Storage, export_csv, export_json
from fbscraper.ai_analysis import DealAnalyzer, is_ai_available

from .schemas import (
    SearchRequest, SearchResultResponse, DealResponse, ListingResponse,
    MarketEstimateResponse, SearchRunResponse, QuickScoreRequest, StatsResponse,
)

logger = logging.getLogger(__name__)

# Shared instances
pricing_engine = PricingEngine()
scorer = DealScorer(pricing_engine)
storage = Storage()
ai_analyzer = DealAnalyzer()

# Track active scraping jobs
active_jobs: dict[str, dict] = {}

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FB Marketplace Car Scraper API starting up")
    yield
    logger.info("API shutting down")


app = FastAPI(
    title="FB Marketplace Car Scraper",
    description="Find the best car deals on Facebook Marketplace with data-driven analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helper: convert DealScore to API response
# ---------------------------------------------------------------------------

def deal_to_response(score) -> DealResponse:
    l = score.listing
    m = score.market_estimate
    return DealResponse(
        ratio=round(score.ratio, 3),
        quality=score.quality.value,
        condition=score.condition.value,
        potential_profit=score.potential_profit,
        notes=score.notes,
        listing=ListingResponse(
            price=l.price,
            year=l.year,
            make=l.make,
            model=l.model,
            mileage=l.mileage,
            location=l.location,
            url=l.url,
        ),
        market_estimate=MarketEstimateResponse(
            trade_in=m.trade_in,
            private_party=m.private_party,
            dealer_retail=m.dealer_retail,
            source=m.source,
        ),
    )


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard."""
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    return HTMLResponse(content="<h1>FB Marketplace Car Scraper</h1><p>Dashboard coming soon. API docs at <a href='/docs'>/docs</a></p>")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/status")
async def get_status():
    """System status check."""
    return {
        "status": "ok",
        "playwright_available": is_playwright_available(),
        "session_active": has_valid_session(),
        "ai_available": is_ai_available(),
        "active_jobs": len(active_jobs),
        "login_in_progress": active_jobs.get("login", {}).get("status") == "in_progress",
    }


@app.post("/api/login")
async def start_login():
    """Launch interactive Facebook login in a visible browser window.

    Opens a Chromium browser on the server machine. The user logs in
    manually, and the session is saved for future headless scraping.
    """
    if not is_playwright_available():
        raise HTTPException(status_code=503, detail="Playwright not installed")

    if active_jobs.get("login", {}).get("status") == "in_progress":
        raise HTTPException(status_code=409, detail="Login already in progress")

    active_jobs["login"] = {"status": "in_progress", "started_at": datetime.now().isoformat()}

    async def do_login():
        try:
            config = SearchConfig()
            scraper = FacebookScraper(config, headless=False)
            success = await asyncio.to_thread(scraper.login_interactive)
            active_jobs["login"] = {
                "status": "completed" if success else "failed",
                "success": success,
                "finished_at": datetime.now().isoformat(),
            }
        except Exception as e:
            active_jobs["login"] = {"status": "failed", "error": str(e)}

    asyncio.create_task(do_login())

    return {
        "message": "Login browser launched. Log in to Facebook in the browser window that just opened.",
        "status": "in_progress",
    }


@app.get("/api/login/status")
async def get_login_status():
    """Check the status of an in-progress login."""
    login_state = active_jobs.get("login", {"status": "idle"})
    return {
        **login_state,
        "session_active": has_valid_session(),
    }


@app.post("/api/search", response_model=SearchResultResponse)
async def run_search(request: SearchRequest):
    """Trigger a marketplace search and return scored deals."""
    config = SearchConfig(
        location=request.location,
        search_term=request.search_term,
        min_price=request.min_price,
        max_price=request.max_price,
        min_year=request.min_year,
        max_year=request.max_year,
        max_mileage=request.max_mileage,
        make=request.make,
        model=request.model,
        scroll_count=request.scroll_count,
    )

    if not is_playwright_available():
        raise HTTPException(status_code=503, detail="Playwright not installed")

    if not has_valid_session():
        raise HTTPException(status_code=401, detail="No active Facebook session. Run: python -m fbscraper --login")

    # Run scraping in thread pool (Playwright is sync)
    scraper = FacebookScraper(config)
    listings = await asyncio.to_thread(scraper.scrape)

    if not listings:
        raise HTTPException(status_code=404, detail="No listings found. Session may have expired.")

    # Score deals
    scores = scorer.score_batch(listings)

    # Save to database
    run_id = storage.save_search_run(config, scores)

    # Export files
    export_csv(scores)
    export_json(scores)

    # Build response
    deals = [deal_to_response(s) for s in scores]

    return SearchResultResponse(
        run_id=run_id,
        total_deals=len(deals),
        excellent_count=sum(1 for s in scores if s.quality == DealQuality.EXCELLENT),
        good_count=sum(1 for s in scores if s.quality == DealQuality.GOOD),
        fair_count=sum(1 for s in scores if s.quality == DealQuality.FAIR),
        poor_count=sum(1 for s in scores if s.quality == DealQuality.POOR),
        deals=deals,
    )


@app.post("/api/score", response_model=DealResponse)
async def quick_score(request: QuickScoreRequest):
    """Score a single car listing without scraping."""
    listing = CarListing(
        price=request.price,
        year=request.year,
        make=request.make,
        model=request.model,
        mileage=request.mileage,
    )

    score = scorer.score(listing)
    return deal_to_response(score)


@app.post("/api/analyze")
async def analyze_deal(request: QuickScoreRequest):
    """AI-powered analysis of a single car deal."""
    listing = CarListing(
        price=request.price,
        year=request.year,
        make=request.make,
        model=request.model,
        mileage=request.mileage,
    )
    score = scorer.score(listing)
    analysis = await asyncio.to_thread(ai_analyzer.analyze_deal, score)
    return {
        "deal": deal_to_response(score).model_dump(),
        "analysis": analysis,
    }


@app.post("/api/analyze/batch")
async def analyze_batch_deals(request: SearchRequest):
    """AI-powered market analysis on recent search results."""
    # Use the most recent search run
    runs = storage.get_recent_runs(1)
    if not runs:
        raise HTTPException(status_code=404, detail="No search data available. Run a search first.")

    # Re-score from stored data to get DealScore objects
    run_data = storage.get_run_scores(runs[0]["id"])
    if not run_data:
        raise HTTPException(status_code=404, detail="No deals in last search run")

    # Reconstruct DealScore objects from stored data
    scores = []
    for row in run_data:
        listing = CarListing(
            price=row["price"], year=row["year"], make=row["make"],
            model=row["model"], mileage=row.get("mileage"),
            location=row.get("location", ""), url=row.get("url", ""),
        )
        scores.append(scorer.score(listing))

    analysis = await asyncio.to_thread(ai_analyzer.analyze_batch, scores)
    return {"total_deals": len(scores), "analysis": analysis}


@app.get("/api/history", response_model=list[SearchRunResponse])
async def get_history(limit: int = Query(default=20, ge=1, le=100)):
    """Get recent search runs."""
    runs = storage.get_recent_runs(limit)
    return [
        SearchRunResponse(
            id=r["id"],
            timestamp=r["timestamp"],
            location=r["location"] or "",
            search_term=r["search_term"] or "",
            listing_count=r["listing_count"],
        )
        for r in runs
    ]


@app.get("/api/history/{run_id}")
async def get_run_details(run_id: int):
    """Get all scored deals from a specific search run."""
    rows = storage.get_run_scores(run_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Run not found")

    return {
        "run_id": run_id,
        "total_deals": len(rows),
        "deals": rows,
    }


@app.get("/api/search/listings")
async def search_listings(
    make: str = Query(default="", description="Filter by make"),
    model: str = Query(default="", description="Filter by model"),
    max_price: int = Query(default=0, ge=0, description="Maximum price"),
    min_year: int = Query(default=0, ge=0, description="Minimum year"),
):
    """Search historical listings across all runs."""
    results = storage.search_listings(
        make=make,
        model=model,
        max_price=max_price,
        min_year=min_year,
    )
    return {"total": len(results), "listings": results}


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get aggregate statistics across all search runs."""
    runs = storage.get_recent_runs(1000)
    total_runs = len(runs)
    total_listings = sum(r["listing_count"] for r in runs)

    # Get top deals
    all_scores = []
    for run in runs[:10]:  # Last 10 runs
        rows = storage.get_run_scores(run["id"])
        all_scores.extend(rows)

    if not all_scores:
        return StatsResponse(
            total_listings=total_listings,
            total_runs=total_runs,
            avg_deal_ratio=0.0,
            best_deal_ratio=0.0,
            top_makes=[],
            recent_excellent_deals=[],
        )

    ratios = [r["ratio"] for r in all_scores if r.get("ratio")]
    avg_ratio = sum(ratios) / len(ratios) if ratios else 0.0
    best_ratio = max(ratios) if ratios else 0.0

    # Top makes by count
    make_counts: dict[str, int] = {}
    for s in all_scores:
        make = s.get("make", "Unknown")
        make_counts[make] = make_counts.get(make, 0) + 1

    top_makes = sorted(
        [{"make": k, "count": v} for k, v in make_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # Recent excellent deals
    excellent = [
        s for s in all_scores
        if s.get("quality") == "Excellent"
    ][:5]

    excellent_responses = []
    for s in excellent:
        excellent_responses.append(DealResponse(
            ratio=s.get("ratio", 0),
            quality=s.get("quality", "Unknown"),
            condition=s.get("condition", "Unknown"),
            potential_profit=s.get("potential_profit", 0),
            notes=s.get("notes", ""),
            listing=ListingResponse(
                price=s.get("price", 0),
                year=s.get("year", 0),
                make=s.get("make", ""),
                model=s.get("model", ""),
                mileage=s.get("mileage"),
                location=s.get("location", ""),
                url=s.get("url", ""),
            ),
            market_estimate=MarketEstimateResponse(
                trade_in=s.get("trade_in", 0),
                private_party=s.get("private_party", 0),
                dealer_retail=s.get("dealer_retail", 0),
                source=s.get("pricing_source", ""),
            ),
        ))

    return StatsResponse(
        total_listings=total_listings,
        total_runs=total_runs,
        avg_deal_ratio=round(avg_ratio, 3),
        best_deal_ratio=round(best_ratio, 3),
        top_makes=top_makes,
        recent_excellent_deals=excellent_responses,
    )


# ---------------------------------------------------------------------------
# WebSocket for live scrape progress
# ---------------------------------------------------------------------------

@app.websocket("/ws/search")
async def websocket_search(websocket: WebSocket):
    """WebSocket endpoint for live search with progress updates."""
    await websocket.accept()

    try:
        # Receive search config
        data = await websocket.receive_json()
        config = SearchConfig(
            location=data.get("location", "atlanta"),
            search_term=data.get("search_term", ""),
            min_price=data.get("min_price", 250),
            max_price=data.get("max_price", 55000),
            min_year=data.get("min_year", 1995),
            max_year=data.get("max_year", 2025),
            max_mileage=data.get("max_mileage", 200000),
            make=data.get("make", ""),
            model=data.get("model", ""),
            scroll_count=data.get("scroll_count", 10),
        )

        if not is_playwright_available():
            await websocket.send_json({"type": "error", "message": "Playwright not installed"})
            return

        if not has_valid_session():
            await websocket.send_json({"type": "error", "message": "No Facebook session. Run --login first."})
            return

        await websocket.send_json({"type": "progress", "message": "Starting search...", "percent": 0})

        # Create scraper with progress callback that sends over WebSocket
        scraper = FacebookScraper(config)
        progress_queue = asyncio.Queue()

        def on_progress(msg: str, pct: int):
            try:
                progress_queue.put_nowait({"type": "progress", "message": msg, "percent": pct})
            except asyncio.QueueFull:
                pass

        scraper.set_progress_callback(on_progress)

        # Run scrape in background thread
        scrape_task = asyncio.create_task(asyncio.to_thread(scraper.scrape))

        # Forward progress updates while scraping
        while not scrape_task.done():
            try:
                update = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                await websocket.send_json(update)
            except asyncio.TimeoutError:
                continue

        listings = scrape_task.result()

        if not listings:
            await websocket.send_json({"type": "error", "message": "No listings found"})
            return

        await websocket.send_json({"type": "progress", "message": f"Scoring {len(listings)} deals...", "percent": 80})

        # Score deals
        scores = scorer.score_batch(listings)
        run_id = storage.save_search_run(config, scores)
        export_csv(scores)

        await websocket.send_json({"type": "progress", "message": "Complete!", "percent": 100})

        # Send results
        deals = [deal_to_response(s).model_dump() for s in scores]
        await websocket.send_json({
            "type": "results",
            "run_id": run_id,
            "total_deals": len(deals),
            "excellent_count": sum(1 for s in scores if s.quality == DealQuality.EXCELLENT),
            "good_count": sum(1 for s in scores if s.quality == DealQuality.GOOD),
            "fair_count": sum(1 for s in scores if s.quality == DealQuality.FAIR),
            "poor_count": sum(1 for s in scores if s.quality == DealQuality.POOR),
            "deals": deals,
        })

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass

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
    SearchRequest, MultiCitySearchRequest, SearchResultResponse, DealResponse,
    ListingResponse, MarketEstimateResponse, FlipEstimateResponse,
    SearchRunResponse, QuickScoreRequest, StatsResponse,
    WatchlistAddRequest, WatchlistUpdateRequest, WatchlistFinancialsRequest,
    WatchlistItemResponse, WatchlistStatsResponse,
    MessageGenerateRequest, MessageGenerateResponse,
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
    flip = None
    if hasattr(score, 'flip_estimate') and score.flip_estimate:
        f = score.flip_estimate
        flip = FlipEstimateResponse(
            purchase_price=f.purchase_price,
            estimated_repair=f.estimated_repair,
            detailing=f.detailing,
            listing_fees=f.listing_fees,
            transport=f.transport,
            total_cost=f.total_cost,
            sell_price=f.sell_price,
            net_profit=f.net_profit,
            roi_percent=f.roi_percent,
        )
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
        flip_estimate=flip,
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


@app.post("/api/search/multi")
async def run_multi_city_search(request: MultiCitySearchRequest):
    """Search across multiple cities and combine results."""
    if not is_playwright_available():
        raise HTTPException(status_code=503, detail="Playwright not installed")
    if not has_valid_session():
        raise HTTPException(status_code=401, detail="No active Facebook session")

    all_listings = []
    city_results = {}

    for city in request.locations:
        config = SearchConfig(
            location=city,
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
        scraper = FacebookScraper(config)
        listings = await asyncio.to_thread(scraper.scrape)
        all_listings.extend(listings)
        city_results[city] = len(listings)

    if not all_listings:
        raise HTTPException(status_code=404, detail="No listings found in any city")

    scores = scorer.score_batch(all_listings)
    config_combined = SearchConfig(
        location=",".join(request.locations),
        search_term=request.search_term,
        min_price=request.min_price,
        max_price=request.max_price,
    )
    run_id = storage.save_search_run(config_combined, scores)
    export_csv(scores)

    deals = [deal_to_response(s) for s in scores]
    return {
        "run_id": run_id,
        "total_deals": len(deals),
        "city_breakdown": city_results,
        "excellent_count": sum(1 for s in scores if s.quality == DealQuality.EXCELLENT),
        "good_count": sum(1 for s in scores if s.quality == DealQuality.GOOD),
        "fair_count": sum(1 for s in scores if s.quality == DealQuality.FAIR),
        "poor_count": sum(1 for s in scores if s.quality == DealQuality.POOR),
        "deals": deals,
    }


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
# Watchlist / Deal Pipeline
# ---------------------------------------------------------------------------

VALID_STAGES = {"watching", "contacted", "inspecting", "negotiating", "purchased", "listed", "sold", "passed"}


@app.post("/api/watchlist", response_model=WatchlistItemResponse)
async def add_to_watchlist(request: WatchlistAddRequest):
    """Add a deal to the watchlist."""
    wid = storage.add_to_watchlist(
        url=request.url,
        price=request.price,
        year=request.year,
        make=request.make,
        model=request.model,
        mileage=request.mileage,
        location=request.location,
    )
    items = storage.get_watchlist()
    item = next((i for i in items if i["id"] == wid), None)
    if not item:
        raise HTTPException(status_code=500, detail="Failed to retrieve watchlist item")
    return WatchlistItemResponse(**item)


@app.get("/api/watchlist/stats", response_model=WatchlistStatsResponse)
async def get_watchlist_stats():
    """Get pipeline statistics."""
    stats = storage.get_watchlist_stats()
    return WatchlistStatsResponse(**stats)


@app.get("/api/watchlist", response_model=list[WatchlistItemResponse])
async def get_watchlist(stage: Optional[str] = Query(default=None)):
    """Get all watchlist items, optionally filtered by stage."""
    if stage and stage not in VALID_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {', '.join(sorted(VALID_STAGES))}")
    items = storage.get_watchlist(stage=stage)
    return [WatchlistItemResponse(**i) for i in items]


@app.put("/api/watchlist/{watchlist_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(watchlist_id: int, request: WatchlistUpdateRequest):
    """Update stage and/or notes for a watchlist item."""
    if request.stage and request.stage not in VALID_STAGES:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Must be one of: {', '.join(sorted(VALID_STAGES))}")
    if request.stage is not None or request.notes is not None:
        # Get existing item to preserve current stage if not being updated
        existing = storage.get_watchlist()
        existing_item = next((i for i in existing if i["id"] == watchlist_id), None)
        if not existing_item:
            raise HTTPException(status_code=404, detail="Watchlist item not found")
        stage = request.stage if request.stage is not None else existing_item["stage"]
        notes = request.notes if request.notes is not None else existing_item.get("notes", "")
        storage.update_watchlist_stage(watchlist_id, stage, notes)
    items = storage.get_watchlist()
    item = next((i for i in items if i["id"] == watchlist_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return WatchlistItemResponse(**item)


@app.put("/api/watchlist/{watchlist_id}/financials", response_model=WatchlistItemResponse)
async def update_watchlist_financials(watchlist_id: int, request: WatchlistFinancialsRequest):
    """Update purchase_price, repair_cost, and/or sell_price."""
    storage.update_watchlist_financials(
        watchlist_id,
        purchase_price=request.purchase_price,
        repair_cost=request.repair_cost,
        sell_price=request.sell_price,
    )
    items = storage.get_watchlist()
    item = next((i for i in items if i["id"] == watchlist_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return WatchlistItemResponse(**item)


@app.delete("/api/watchlist/{watchlist_id}")
async def remove_from_watchlist(watchlist_id: int):
    """Remove a deal from the watchlist."""
    storage.remove_from_watchlist(watchlist_id)
    return {"detail": "removed", "id": watchlist_id}


# ---------------------------------------------------------------------------
# Seller Messages
# ---------------------------------------------------------------------------

@app.post("/api/messages", response_model=MessageGenerateResponse)
async def generate_messages(request: MessageGenerateRequest):
    """Generate seller message templates for a listing."""
    listing = CarListing(
        price=request.price,
        year=request.year,
        make=request.make,
        model=request.model,
        mileage=request.mileage,
    )
    score = scorer.score(listing)
    result = await asyncio.to_thread(ai_analyzer.generate_seller_message, score)
    return MessageGenerateResponse(**result)


# ---------------------------------------------------------------------------
# Export Endpoints
# ---------------------------------------------------------------------------

OUTPUT_DIR = Path(__file__).parent.parent / "output"


@app.get("/api/export/csv")
async def export_csv_endpoint(run_id: Optional[int] = Query(default=None)):
    """Download CSV file for a specific run (or latest if no run_id)."""
    target_run_id = run_id
    if target_run_id is None:
        runs = storage.get_recent_runs(1)
        if not runs:
            raise HTTPException(status_code=404, detail="No search runs found")
        target_run_id = runs[0]["id"]

    rows = storage.get_run_scores(target_run_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for run {target_run_id}")

    # Build CSV in output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    import csv
    filename = f"run_{target_run_id}.csv"
    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Deal_Ratio", "Quality", "Condition", "Potential_Profit",
            "Price", "Year", "Make", "Model", "Mileage", "Location",
            "Market_TradeIn", "Market_PrivateParty", "Market_DealerRetail",
            "Pricing_Source", "Facebook_URL", "Notes",
        ])
        for r in rows:
            writer.writerow([
                r.get("ratio", ""), r.get("quality", ""), r.get("condition", ""),
                r.get("potential_profit", ""),
                r.get("price", ""), r.get("year", ""), r.get("make", ""), r.get("model", ""),
                r.get("mileage", ""), r.get("location", ""),
                r.get("trade_in", ""), r.get("private_party", ""), r.get("dealer_retail", ""),
                r.get("pricing_source", ""), r.get("url", ""), r.get("notes", ""),
            ])

    return FileResponse(
        path=str(filepath),
        media_type="text/csv",
        filename=filename,
    )


@app.get("/api/export/json")
async def export_json_endpoint(run_id: Optional[int] = Query(default=None)):
    """Download JSON file for a specific run (or latest if no run_id)."""
    target_run_id = run_id
    if target_run_id is None:
        runs = storage.get_recent_runs(1)
        if not runs:
            raise HTTPException(status_code=404, detail="No search runs found")
        target_run_id = runs[0]["id"]

    rows = storage.get_run_scores(target_run_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for run {target_run_id}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"run_{target_run_id}.json"
    filepath = OUTPUT_DIR / filename

    data = {
        "run_id": target_run_id,
        "exported_at": datetime.now().isoformat(),
        "total_deals": len(rows),
        "deals": rows,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return FileResponse(
        path=str(filepath),
        media_type="application/json",
        filename=filename,
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

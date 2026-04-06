"""Storage module: SQLite database + CSV/JSON export."""

import csv
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import CarListing, DealScore, MarketEstimate, DealQuality, MileageCondition

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output"
DB_PATH = Path(__file__).parent.parent / "data" / "fbscraper.db"


class Storage:
    """Persistent storage for car listings and deal scores."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS search_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    location TEXT,
                    search_term TEXT,
                    listing_count INTEGER,
                    config_json TEXT
                );

                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    listing_id TEXT,
                    price INTEGER,
                    year INTEGER,
                    make TEXT,
                    model TEXT,
                    mileage INTEGER,
                    location TEXT,
                    url TEXT,
                    scraped_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES search_runs(id)
                );

                CREATE TABLE IF NOT EXISTS deal_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    ratio REAL,
                    quality TEXT,
                    condition TEXT,
                    potential_profit INTEGER,
                    trade_in INTEGER,
                    private_party INTEGER,
                    dealer_retail INTEGER,
                    pricing_source TEXT,
                    notes TEXT,
                    FOREIGN KEY (listing_id) REFERENCES listings(id)
                );

                CREATE INDEX IF NOT EXISTS idx_listings_make_model ON listings(make, model);
                CREATE INDEX IF NOT EXISTS idx_listings_year ON listings(year);
                CREATE INDEX IF NOT EXISTS idx_listings_scraped ON listings(scraped_at);
                CREATE INDEX IF NOT EXISTS idx_scores_ratio ON deal_scores(ratio);
                CREATE INDEX IF NOT EXISTS idx_scores_quality ON deal_scores(quality);
            """)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def save_search_run(self, config, scores: list[DealScore]) -> int:
        """Save a complete search run with all scored listings."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO search_runs (timestamp, location, search_term, listing_count, config_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(),
                    getattr(config, "location", ""),
                    getattr(config, "search_term", ""),
                    len(scores),
                    json.dumps(config.__dict__) if hasattr(config, "__dict__") else "{}",
                ),
            )
            run_id = cursor.lastrowid

            for score in scores:
                listing = score.listing
                cursor = conn.execute(
                    "INSERT INTO listings (run_id, listing_id, price, year, make, model, "
                    "mileage, location, url, scraped_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        listing.listing_id,
                        listing.price,
                        listing.year,
                        listing.make,
                        listing.model,
                        listing.mileage,
                        listing.location,
                        listing.url,
                        listing.scraped_at.isoformat(),
                    ),
                )
                db_listing_id = cursor.lastrowid

                conn.execute(
                    "INSERT INTO deal_scores (listing_id, ratio, quality, condition, "
                    "potential_profit, trade_in, private_party, dealer_retail, pricing_source, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        db_listing_id,
                        score.ratio,
                        score.quality.value,
                        score.condition.value,
                        score.potential_profit,
                        score.market_estimate.trade_in,
                        score.market_estimate.private_party,
                        score.market_estimate.dealer_retail,
                        score.market_estimate.source,
                        score.notes,
                    ),
                )

            conn.commit()
            logger.info("Saved search run #%d with %d listings", run_id, len(scores))
            return run_id

    def get_recent_runs(self, limit: int = 10) -> list[dict]:
        """Get recent search runs."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM search_runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_run_scores(self, run_id: int) -> list[dict]:
        """Get all scored listings for a search run."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT l.*, d.ratio, d.quality, d.condition, d.potential_profit,
                       d.trade_in, d.private_party, d.dealer_retail, d.pricing_source, d.notes
                FROM listings l
                JOIN deal_scores d ON d.listing_id = l.id
                WHERE l.run_id = ?
                ORDER BY d.ratio DESC
                """,
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def search_listings(self, make: str = "", model: str = "", max_price: int = 0,
                        min_year: int = 0, days_back: int = 30) -> list[dict]:
        """Search historical listings."""
        query = """
            SELECT l.*, d.ratio, d.quality, d.potential_profit
            FROM listings l
            JOIN deal_scores d ON d.listing_id = l.id
            WHERE 1=1
        """
        params = []

        if make:
            query += " AND LOWER(l.make) = LOWER(?)"
            params.append(make)
        if model:
            query += " AND LOWER(l.model) = LOWER(?)"
            params.append(model)
        if max_price > 0:
            query += " AND l.price <= ?"
            params.append(max_price)
        if min_year > 0:
            query += " AND l.year >= ?"
            params.append(min_year)

        query += " ORDER BY d.ratio DESC LIMIT 100"

        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]


def export_csv(scores: list[DealScore], filename: Optional[str] = None) -> str:
    """Export deal scores to CSV file in the output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"deals_{timestamp}.csv"

    filepath = OUTPUT_DIR / filename

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Deal_Ratio", "Quality", "Condition", "Potential_Profit",
            "Price", "Year", "Make", "Model", "Mileage", "Location",
            "Market_TradeIn", "Market_PrivateParty", "Market_DealerRetail",
            "Pricing_Source", "Facebook_URL", "Notes",
        ])

        for score in scores:
            l = score.listing
            m = score.market_estimate
            writer.writerow([
                score.ratio, score.quality.value, score.condition.value,
                score.potential_profit,
                l.price, l.year, l.make, l.model,
                l.mileage or "Unknown", l.location,
                m.trade_in, m.private_party, m.dealer_retail, m.source,
                l.url, score.notes,
            ])

    logger.info("Exported %d deals to %s", len(scores), filepath)
    return str(filepath)


def export_json(scores: list[DealScore], filename: Optional[str] = None) -> str:
    """Export deal scores to JSON file in the output directory."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if filename is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"deals_{timestamp}.json"

    filepath = OUTPUT_DIR / filename

    data = {
        "exported_at": datetime.now().isoformat(),
        "total_deals": len(scores),
        "deals": [score.to_dict() for score in scores],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.info("Exported %d deals to %s", len(scores), filepath)
    return str(filepath)

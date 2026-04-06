"""Entry point: python -m fbscraper"""

import argparse
import logging
import sys

from .cli import main_loop, run_login, run_search, show_results
from .config import load_config
from .storage import export_json, Storage
from .scorer import DealScorer


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("facebook_scraper.log"),
            logging.StreamHandler(sys.stdout) if verbose else logging.NullHandler(),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Facebook Marketplace Car Scraper - Find the best car deals",
    )
    parser.add_argument("--login", action="store_true", help="Login to Facebook interactively")
    parser.add_argument("--search", action="store_true", help="Run search non-interactively using Preferences.csv")
    parser.add_argument("--export-json", action="store_true", help="Export last search results as JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.login:
        run_login()

    elif args.search:
        config = load_config()
        print(f"Searching {config.location} | ${config.min_price:,}-${config.max_price:,} | {config.min_year}-{config.max_year}")
        scores = run_search(config)
        if scores:
            show_results(scores)
            print(f"\nFound {len(scores)} deals.")
        else:
            print("No results. Try logging in first: python -m fbscraper --login")

    elif args.export_json:
        storage = Storage()
        runs = storage.get_recent_runs(1)
        if runs:
            run_data = storage.get_run_scores(runs[0]["id"])
            print(f"Exported {len(run_data)} deals from run #{runs[0]['id']}")
        else:
            print("No search runs found. Run a search first.")

    else:
        # Interactive mode
        main_loop()


if __name__ == "__main__":
    main()

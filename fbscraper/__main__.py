"""Entry point: python -m fbscraper"""

import argparse
import logging
import sys

from .cli import main_loop, run_login, run_search, run_value_cli, run_value_lookup, show_results
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
        description="Facebook Marketplace Car Flipper - Find & value the best car deals",
        prog="fbscraper",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # value subcommand
    value_parser = subparsers.add_parser(
        "value",
        help="Look up real-time KBB/Edmunds value for a car",
        description="Look up current market value using web search (KBB, Edmunds, NADA)",
    )
    value_parser.add_argument("car", nargs="*", help="Year Make Model (e.g. 2019 Toyota Camry)")
    value_parser.add_argument("--year", "-y", type=int, help="Model year")
    value_parser.add_argument("--make", "-mk", help="Manufacturer (e.g. Toyota)")
    value_parser.add_argument("--model", "-md", help="Model name (e.g. Camry)")
    value_parser.add_argument("--mileage", "-mi", type=int, help="Odometer reading")
    value_parser.add_argument("--trim", "-t", help="Trim level (e.g. SE, XLE)")
    value_parser.add_argument("--condition", "-c", choices=["excellent", "good", "fair", "poor"], help="Vehicle condition")

    # search subcommand
    search_parser = subparsers.add_parser(
        "search",
        help="Search Facebook Marketplace for car deals",
    )
    search_parser.add_argument("--location", "-l", help="Override search location")
    search_parser.add_argument("--make", help="Filter by make")
    search_parser.add_argument("--model", help="Filter by model")
    search_parser.add_argument("--min-price", type=int, help="Minimum price")
    search_parser.add_argument("--max-price", type=int, help="Maximum price")
    search_parser.add_argument("--min-year", type=int, help="Minimum year")
    search_parser.add_argument("--max-year", type=int, help="Maximum year")

    # login subcommand
    subparsers.add_parser("login", help="Log in to Facebook interactively")

    # history subcommand
    subparsers.add_parser("history", help="View past search results")

    # export subcommand
    export_parser = subparsers.add_parser("export", help="Export results")
    export_parser.add_argument("--format", choices=["json", "csv"], default="json", help="Export format")

    # Legacy flags (backwards compatible)
    parser.add_argument("--login", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--search", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--export-json", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Handle subcommands
    if args.command == "value":
        run_value_cli(args)

    elif args.command == "search":
        config = load_config()
        # Apply CLI overrides
        if args.location:
            config.location = args.location
        if args.make:
            config.make = args.make
        if args.model:
            config.model = args.model
        if args.min_price is not None:
            config.min_price = args.min_price
        if args.max_price is not None:
            config.max_price = args.max_price
        if args.min_year is not None:
            config.min_year = args.min_year
        if args.max_year is not None:
            config.max_year = args.max_year

        print(f"Searching {config.location} | ${config.min_price:,}-${config.max_price:,} | {config.min_year}-{config.max_year}")
        scores = run_search(config)
        if scores:
            show_results(scores)
            print(f"\nFound {len(scores)} deals.")
        else:
            print("No results. Try logging in first: python -m fbscraper login")

    elif args.command == "login":
        run_login()

    elif args.command == "history":
        from .cli import show_history
        show_history()

    elif args.command == "export":
        storage = Storage()
        runs = storage.get_recent_runs(1)
        if runs:
            run_data = storage.get_run_scores(runs[0]["id"])
            print(f"Exported {len(run_data)} deals from run #{runs[0]['id']}")
        else:
            print("No search runs found. Run a search first.")

    # Legacy flag support
    elif args.login:
        run_login()

    elif args.search:
        config = load_config()
        print(f"Searching {config.location} | ${config.min_price:,}-${config.max_price:,} | {config.min_year}-{config.max_year}")
        scores = run_search(config)
        if scores:
            show_results(scores)
            print(f"\nFound {len(scores)} deals.")
        else:
            print("No results. Try logging in first: python -m fbscraper login")

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

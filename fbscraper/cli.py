"""Rich CLI interface for the Facebook Marketplace Car Scraper."""

import logging
import sys
import time
from typing import Optional

from .config import load_config, save_config
from .models import DealQuality, DealScore, MileageCondition, SearchConfig
from .pricing import PricingEngine
from .scorer import DealScorer
from .scraper import FacebookScraper, has_valid_session, is_playwright_available
from .storage import Storage, export_csv, export_json
from .web_pricing import WebPricingEngine

logger = logging.getLogger(__name__)

# Rich imports (graceful fallback)
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.rule import Rule
    from rich.align import Align
    from rich import box
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

console = Console() if RICH_AVAILABLE else None


def print_msg(msg: str) -> None:
    """Print a message, using Rich if available."""
    if console:
        console.print(msg)
    else:
        print(msg)


# ---------------------------------------------------------------------------
# Welcome & Menu
# ---------------------------------------------------------------------------

def show_welcome() -> None:
    if not RICH_AVAILABLE:
        print("\n=== Facebook Marketplace Car Scraper v1.0 ===\n")
        return

    content = "[bold blue]Facebook Marketplace Car Scraper[/bold blue]\n"
    content += "[italic cyan]Find the best car deals with data-driven analysis[/italic cyan]\n\n"
    content += "[bold]System Status:[/bold]\n"

    if is_playwright_available():
        content += "  [green]Playwright[/green] - Web scraping ready\n"
    else:
        content += "  [red]Playwright[/red] - Not installed\n"

    if has_valid_session():
        content += "  [green]Facebook Session[/green] - Active\n"
    else:
        content += "  [yellow]Facebook Session[/yellow] - Not logged in\n"

    web_pricing = WebPricingEngine()
    if web_pricing.is_available():
        content += "  [green]Live Pricing[/green] - KBB/Edmunds via web search\n"
    else:
        content += "  [yellow]Live Pricing[/yellow] - Set ANTHROPIC_API_KEY for real-time values\n"

    content += "  [green]Rich CLI[/green] - Enhanced interface active"

    panel = Panel(
        Align.center(content),
        title="[bold]Welcome[/bold]",
        border_style="blue",
        padding=(1, 3),
    )
    console.print("\n")
    console.print(panel)
    console.print()


def show_menu() -> str:
    if not RICH_AVAILABLE:
        print("\n--- MAIN MENU ---")
        print("1. Search Cars")
        print("2. Value a Car (KBB Lookup)")
        print("3. Configure Settings")
        print("4. Login to Facebook")
        print("5. View History")
        print("6. Help")
        print("7. Exit")
        choice = input("Select (1-7): ").strip()
        return {
            "1": "search", "2": "value", "3": "configure", "4": "login",
            "5": "history", "6": "help", "7": "exit",
        }.get(choice, "invalid")

    console.print(Rule("[bold blue]Main Menu[/bold blue]"))

    menu = Table(show_header=False, box=None, padding=(0, 2))
    menu.add_column(style="cyan", min_width=3)
    menu.add_column(style="bold", min_width=20)
    menu.add_column(style="dim")

    menu.add_row("1.", "search", "Search Facebook Marketplace for car deals")
    menu.add_row("2.", "value", "Look up KBB/Edmunds value for any car")
    menu.add_row("3.", "configure", "Modify search preferences")
    menu.add_row("4.", "login", "Log in to Facebook (save session)")
    menu.add_row("5.", "history", "View past search results")
    menu.add_row("6.", "help", "Show help and usage info")
    menu.add_row("7.", "exit", "Exit the application")

    console.print(menu)
    console.print()

    return Prompt.ask(
        "[bold cyan]Select an option[/bold cyan]",
        choices=["search", "value", "configure", "login", "history", "help", "exit"],
        default="search",
    )


# ---------------------------------------------------------------------------
# Search Configuration
# ---------------------------------------------------------------------------

def get_search_config() -> SearchConfig:
    """Interactive search configuration."""
    config = load_config()

    if not RICH_AVAILABLE:
        return _get_config_plain(config)

    console.print(Rule("[bold green]Search Configuration[/bold green]"))

    search_term = Prompt.ask("Search term", default=config.search_term or "", show_default=True)
    config.search_term = search_term

    location = Prompt.ask("Location", default=config.location)
    config.location = location

    console.print("\n[bold cyan]Price Range[/bold cyan]")
    config.min_price = IntPrompt.ask("Min price ($)", default=config.min_price)
    config.max_price = IntPrompt.ask("Max price ($)", default=config.max_price)

    console.print("\n[bold cyan]Year Range[/bold cyan]")
    config.min_year = IntPrompt.ask("Min year", default=config.min_year)
    config.max_year = IntPrompt.ask("Max year", default=config.max_year)

    config.max_mileage = IntPrompt.ask("Max mileage", default=config.max_mileage)

    # Advanced filters
    console.print(Panel("[bold]Advanced Filters[/bold] [dim](optional, press Enter to skip)[/dim]", border_style="yellow"))

    make = Prompt.ask("Make (e.g. Toyota)", default=config.make or "", show_default=True)
    config.make = make

    model = Prompt.ask("Model (e.g. Camry)", default=config.model or "", show_default=True)
    config.model = model

    transmission = Prompt.ask("Transmission", choices=["", "automatic", "manual"], default=config.transmission or "")
    config.transmission = transmission

    config.scroll_count = IntPrompt.ask("Scroll iterations", default=config.scroll_count)

    return config


def _get_config_plain(config: SearchConfig) -> SearchConfig:
    """Plain text config input (no Rich)."""
    search = input(f"Search term [{config.search_term or 'any'}]: ").strip()
    if search:
        config.search_term = search

    loc = input(f"Location [{config.location}]: ").strip()
    if loc:
        config.location = loc

    try:
        val = input(f"Min price [{config.min_price}]: ").strip()
        if val:
            config.min_price = int(val)
    except ValueError:
        pass

    try:
        val = input(f"Max price [{config.max_price}]: ").strip()
        if val:
            config.max_price = int(val)
    except ValueError:
        pass

    try:
        val = input(f"Min year [{config.min_year}]: ").strip()
        if val:
            config.min_year = int(val)
    except ValueError:
        pass

    try:
        val = input(f"Max year [{config.max_year}]: ").strip()
        if val:
            config.max_year = int(val)
    except ValueError:
        pass

    return config


def show_config_summary(config: SearchConfig) -> bool:
    """Show search summary and ask for confirmation."""
    if not RICH_AVAILABLE:
        print(f"\nSearch: {config.search_term or 'Any car'}")
        print(f"Location: {config.location}")
        print(f"Price: ${config.min_price:,} - ${config.max_price:,}")
        print(f"Year: {config.min_year} - {config.max_year}")
        return input("Proceed? (y/n) [y]: ").strip().lower() != "n"

    console.print(Rule("[bold cyan]Search Summary[/bold cyan]"))

    table = Table(box=box.ROUNDED)
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="yellow")

    table.add_row("Search Term", config.search_term or "Any car")
    table.add_row("Location", config.location)
    table.add_row("Price Range", f"${config.min_price:,} - ${config.max_price:,}")
    table.add_row("Year Range", f"{config.min_year} - {config.max_year}")
    table.add_row("Max Mileage", f"{config.max_mileage:,}")
    if config.make:
        table.add_row("Make", config.make)
    if config.model:
        table.add_row("Model", config.model)
    table.add_row("Scroll Count", str(config.scroll_count))

    console.print(table)
    console.print()

    return Confirm.ask("[bold green]Proceed with search?[/bold green]", default=True)


# ---------------------------------------------------------------------------
# Search Execution
# ---------------------------------------------------------------------------

def run_search(config: SearchConfig) -> Optional[list[DealScore]]:
    """Execute the full search pipeline with progress display."""
    scraper = FacebookScraper(config)
    pricing = PricingEngine()
    scorer = DealScorer(pricing)
    storage = Storage()

    if not RICH_AVAILABLE:
        return _run_search_plain(scraper, scorer, storage, config)

    scores = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:

        task = progress.add_task("[cyan]Starting search...", total=100)

        def on_progress(msg: str, pct: int) -> None:
            progress.update(task, completed=pct, description=f"[cyan]{msg}")

        scraper.set_progress_callback(on_progress)

        # Scrape
        listings = scraper.scrape()

        if not listings:
            progress.update(task, completed=100, description="[red]No listings found")
            return None

        progress.update(task, completed=70, description=f"[yellow]Scoring {len(listings)} listings...")

        # Score
        scores = scorer.score_batch(listings)

        progress.update(task, completed=85, description="[yellow]Saving results...")

        # Save to database
        storage.save_search_run(config, scores)

        # Export CSV
        csv_path = export_csv(scores)
        progress.update(task, completed=95, description="[green]Exporting...")

        # Export JSON
        export_json(scores)

        progress.update(task, completed=100, description="[green]Search complete!")

    return scores


def _run_search_plain(scraper, scorer, storage, config) -> Optional[list[DealScore]]:
    """Plain text search (no Rich)."""
    print("\nSearching Facebook Marketplace...")

    listings = scraper.scrape()
    if not listings:
        print("No listings found.")
        return None

    print(f"Found {len(listings)} listings. Scoring...")
    scores = scorer.score_batch(listings)

    storage.save_search_run(config, scores)
    csv_path = export_csv(scores)
    export_json(scores)

    print(f"Results saved to {csv_path}")
    return scores


# ---------------------------------------------------------------------------
# Results Display
# ---------------------------------------------------------------------------

def show_results(scores: list[DealScore]) -> None:
    """Display search results."""
    if not scores:
        print_msg("[yellow]No results to display.[/yellow]" if RICH_AVAILABLE else "No results.")
        return

    if not RICH_AVAILABLE:
        _show_results_plain(scores)
        return

    console.print(Rule("[bold green]Search Results[/bold green]"))
    console.print(f"[dim]Total deals analyzed: {len(scores)}[/dim]\n")

    # Summary stats
    excellent = sum(1 for s in scores if s.quality == DealQuality.EXCELLENT)
    good = sum(1 for s in scores if s.quality == DealQuality.GOOD)
    fair = sum(1 for s in scores if s.quality == DealQuality.FAIR)
    poor = sum(1 for s in scores if s.quality == DealQuality.POOR)

    stats = Table(title="Deal Distribution", box=box.SIMPLE)
    stats.add_column("Quality", style="bold")
    stats.add_column("Count", justify="right")
    stats.add_row("[green]Excellent[/green]", str(excellent))
    stats.add_row("[blue]Good[/blue]", str(good))
    stats.add_row("[yellow]Fair[/yellow]", str(fair))
    stats.add_row("[red]Poor[/red]", str(poor))
    console.print(stats)
    console.print()

    # Top deals table
    table = Table(title="Top Deals", box=box.ROUNDED)
    table.add_column("#", style="dim", width=3)
    table.add_column("Year", justify="right")
    table.add_column("Make")
    table.add_column("Model")
    table.add_column("Price", justify="right", style="green")
    table.add_column("Market Value", justify="right", style="cyan")
    table.add_column("Profit", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Quality")
    table.add_column("Mileage", justify="right")
    table.add_column("Source", style="dim")

    quality_colors = {
        DealQuality.EXCELLENT: "bold green",
        DealQuality.GOOD: "blue",
        DealQuality.FAIR: "yellow",
        DealQuality.POOR: "red",
    }

    for i, score in enumerate(scores[:25], 1):
        l = score.listing
        m = score.market_estimate
        color = quality_colors[score.quality]

        profit_str = f"+${score.potential_profit:,}" if score.potential_profit > 0 else f"-${abs(score.potential_profit):,}"
        profit_color = "green" if score.potential_profit > 0 else "red"
        mileage_str = f"{l.mileage:,}" if l.mileage else "N/A"

        table.add_row(
            str(i),
            str(l.year),
            l.make,
            l.model,
            f"${l.price:,}",
            f"${m.private_party:,}",
            f"[{profit_color}]{profit_str}[/{profit_color}]",
            f"[{color}]{score.ratio:.2f}[/{color}]",
            f"[{color}]{score.quality.value}[/{color}]",
            mileage_str,
            m.source[:8],
        )

    console.print(table)
    console.print()


def _show_results_plain(scores: list[DealScore]) -> None:
    """Plain text results display."""
    print(f"\n=== Results ({len(scores)} deals) ===\n")
    print(f"{'#':>3} {'Year':>4} {'Make':<12} {'Model':<12} {'Price':>8} {'Market':>8} {'Profit':>8} {'Ratio':>6} {'Quality':<9}")
    print("-" * 85)

    for i, score in enumerate(scores[:25], 1):
        l = score.listing
        m = score.market_estimate
        profit = f"+${score.potential_profit:,}" if score.potential_profit > 0 else f"-${abs(score.potential_profit):,}"
        print(f"{i:>3} {l.year:>4} {l.make:<12} {l.model:<12} ${l.price:>7,} ${m.private_party:>7,} {profit:>8} {score.ratio:>5.2f} {score.quality.value:<9}")


# ---------------------------------------------------------------------------
# Login, History, Help
# ---------------------------------------------------------------------------

def run_login() -> None:
    """Run the interactive Facebook login flow."""
    if not is_playwright_available():
        print_msg("[red]Playwright is not installed.[/red]" if RICH_AVAILABLE else "Playwright not installed.")
        return

    print_msg("[cyan]Launching browser for Facebook login...[/cyan]" if RICH_AVAILABLE else "Launching browser...")
    print_msg("[dim]Log in to your Facebook account in the browser window.[/dim]" if RICH_AVAILABLE else "Log in to Facebook in the browser window.")
    print_msg("[dim]The session will be saved for future scraping runs.[/dim]" if RICH_AVAILABLE else "Session will be saved.")

    config = SearchConfig()  # dummy config, not used for login
    scraper = FacebookScraper(config, headless=False)
    success = scraper.login_interactive()

    if success:
        print_msg("[bold green]Login successful! Session saved.[/bold green]" if RICH_AVAILABLE else "Login successful!")
    else:
        print_msg("[bold red]Login failed or timed out.[/bold red]" if RICH_AVAILABLE else "Login failed.")


def show_history() -> None:
    """Show past search runs."""
    storage = Storage()
    runs = storage.get_recent_runs(10)

    if not runs:
        print_msg("[yellow]No search history found.[/yellow]" if RICH_AVAILABLE else "No history.")
        return

    if not RICH_AVAILABLE:
        for run in runs:
            print(f"  Run #{run['id']}: {run['timestamp']} - {run['location']} - {run['listing_count']} listings")
        return

    table = Table(title="Recent Searches", box=box.ROUNDED)
    table.add_column("Run #", style="cyan")
    table.add_column("Date")
    table.add_column("Location")
    table.add_column("Search Term")
    table.add_column("Listings", justify="right")

    for run in runs:
        table.add_row(
            str(run["id"]),
            run["timestamp"][:19],
            run["location"] or "-",
            run["search_term"] or "Any",
            str(run["listing_count"]),
        )

    console.print(table)


def show_help() -> None:
    """Show help information."""
    if not RICH_AVAILABLE:
        print("\n=== Help ===")
        print("1. Login: Log in to Facebook first (saves session for scraping)")
        print("2. Search: Configure filters and scrape Facebook Marketplace")
        print("3. Value: Look up real-time KBB/Edmunds values for any car")
        print("4. Results are saved to output/ as CSV and JSON")
        print("5. Historical data stored in SQLite for trend analysis")
        print("\nCLI usage:")
        print("  python -m fbscraper                              # Interactive mode")
        print("  python -m fbscraper value 2019 Toyota Camry      # Quick KBB lookup")
        print("  python -m fbscraper search                       # Non-interactive search")
        print("  python -m fbscraper login                        # Login to Facebook")
        return

    help_text = """[bold]How to Use:[/bold]

[cyan]1. Value[/cyan] - Look up real-time KBB & Edmunds values for any car.
   Uses Claude web search to fetch current market data.

[cyan]2. Search[/cyan] - Configure price, year, mileage, make/model filters.
   The scraper loads Facebook Marketplace and scrolls to collect listings.

[cyan]3. Login[/cyan] - Log in to Facebook first. A browser window opens where you
   log in manually. Your session is saved for future headless scraping.

[cyan]4. Analysis[/cyan] - Each listing is compared against independent market
   values to calculate a deal ratio and potential profit.

[cyan]5. Results[/cyan] - Deals are saved to output/ as CSV and JSON.
   Historical data is stored in SQLite for trend analysis.

[bold]CLI Commands:[/bold]
  python -m fbscraper                                Interactive mode
  python -m fbscraper value 2019 Toyota Camry        Quick KBB lookup
  python -m fbscraper value 2019 Toyota Camry -mi 50000  With mileage
  python -m fbscraper search                         Search with saved prefs
  python -m fbscraper search --location chicago      Override location
  python -m fbscraper login                          Login to Facebook
  python -m fbscraper history                        View past searches
  python -m fbscraper export --format json           Export results
"""

    console.print(Panel(help_text, title="[bold]Help[/bold]", border_style="blue"))


# ---------------------------------------------------------------------------
# Value Lookup (KBB / Edmunds via Web Search)
# ---------------------------------------------------------------------------

def run_value_lookup(
    year: Optional[int] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    mileage: Optional[int] = None,
    trim: Optional[str] = None,
    condition: Optional[str] = None,
    interactive: bool = True,
) -> None:
    """Look up real-time KBB/Edmunds market value for a vehicle."""
    web_pricing = WebPricingEngine()

    if not web_pricing.is_available():
        print_msg(
            "[red]Live pricing requires ANTHROPIC_API_KEY.[/red]\n"
            "[dim]Set it in your environment: export ANTHROPIC_API_KEY=your_key[/dim]"
            if RICH_AVAILABLE
            else "Live pricing requires ANTHROPIC_API_KEY.\nSet: export ANTHROPIC_API_KEY=your_key"
        )
        return

    # Interactive prompts if values not provided
    if interactive and year is None:
        if RICH_AVAILABLE:
            console.print(Rule("[bold green]Car Value Lookup[/bold green]"))
            console.print("[dim]Look up real-time KBB & Edmunds values via web search[/dim]\n")
            year = IntPrompt.ask("Year", default=2020)
            make = Prompt.ask("Make (e.g. Toyota)")
            model = Prompt.ask("Model (e.g. Camry)")
            trim_input = Prompt.ask("Trim [dim](optional, press Enter to skip)[/dim]", default="")
            trim = trim_input if trim_input else None
            mileage_input = Prompt.ask("Mileage [dim](optional)[/dim]", default="")
            mileage = int(mileage_input) if mileage_input else None
            condition = Prompt.ask(
                "Condition",
                choices=["", "excellent", "good", "fair", "poor"],
                default="good",
            )
            if not condition:
                condition = None
        else:
            year = int(input("Year: ").strip())
            make = input("Make: ").strip()
            model = input("Model: ").strip()
            trim = input("Trim (optional): ").strip() or None
            mil = input("Mileage (optional): ").strip()
            mileage = int(mil) if mil else None
            cond = input("Condition (excellent/good/fair/poor): ").strip()
            condition = cond if cond else None

    if not year or not make or not model:
        print_msg("[red]Year, make, and model are required.[/red]" if RICH_AVAILABLE else "Year, make, and model are required.")
        return

    car_desc = f"{year} {make} {model}"
    if trim:
        car_desc += f" {trim}"

    # Show spinner while searching
    try:
        if RICH_AVAILABLE:
            console.print()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(f"[cyan]Searching KBB & Edmunds for {car_desc}...", total=None)
                data = web_pricing.lookup_detailed(year, make, model, mileage, trim, condition)
                progress.update(task, description="[green]Done!", completed=True)
        else:
            print(f"Looking up {car_desc}...")
            data = web_pricing.lookup_detailed(year, make, model, mileage, trim, condition)
    except RuntimeError as e:
        print_msg(f"[red]{e}[/red]" if RICH_AVAILABLE else str(e))
        return

    if not data:
        print_msg("[red]Could not retrieve pricing data. Try again.[/red]" if RICH_AVAILABLE else "Could not retrieve pricing data.")
        return

    _show_value_results(car_desc, mileage, condition, data)


def _show_value_results(car_desc: str, mileage: Optional[int], condition: Optional[str], data: dict) -> None:
    """Display the value lookup results."""
    if not RICH_AVAILABLE:
        _show_value_results_plain(car_desc, data)
        return

    # Header
    header = f"[bold]{car_desc}[/bold]"
    if mileage:
        header += f" | {mileage:,} miles"
    if condition:
        header += f" | {condition.title()} condition"

    console.print()
    console.print(Panel(header, title="[bold blue]Vehicle Valuation[/bold blue]", border_style="blue"))

    # Main values table
    values_table = Table(title="Market Values", box=box.ROUNDED, show_lines=True)
    values_table.add_column("Category", style="bold", min_width=16)
    values_table.add_column("Value", justify="right", style="green", min_width=12)
    values_table.add_column("Description", style="dim")

    trade_in = data.get("trade_in", 0)
    private_party = data.get("private_party", 0)
    dealer_retail = data.get("dealer_retail", 0)

    values_table.add_row(
        "[cyan]Trade-In[/cyan]",
        f"${trade_in:,}",
        "What a dealer would offer you",
    )
    values_table.add_row(
        "[yellow]Private Party[/yellow]",
        f"${private_party:,}",
        "Selling directly to a buyer",
    )
    values_table.add_row(
        "[red]Dealer Retail[/red]",
        f"${dealer_retail:,}",
        "What a dealer would charge",
    )

    console.print(values_table)

    # KBB and Edmunds ranges if available
    kbb_range = data.get("kbb_range")
    edmunds_range = data.get("edmunds_range")

    if kbb_range or edmunds_range:
        range_table = Table(title="Source Ranges", box=box.SIMPLE)
        range_table.add_column("Source", style="bold")
        range_table.add_column("Low", justify="right")
        range_table.add_column("High", justify="right")

        if kbb_range and kbb_range.get("low"):
            range_table.add_row(
                "KBB",
                f"${kbb_range['low']:,}",
                f"${kbb_range['high']:,}",
            )
        if edmunds_range and edmunds_range.get("low"):
            range_table.add_row(
                "Edmunds",
                f"${edmunds_range['low']:,}",
                f"${edmunds_range['high']:,}",
            )

        console.print(range_table)

    # Flip analysis
    if private_party > 0:
        console.print()
        flip_table = Table(title="Flip Quick Reference", box=box.SIMPLE)
        flip_table.add_column("Buy At", justify="right", style="green")
        flip_table.add_column("Sell At", justify="right", style="cyan")
        flip_table.add_column("Est. Profit", justify="right")
        flip_table.add_column("ROI", justify="right")

        # Show profit at different buy prices
        for buy_pct, label in [(0.65, "Steal"), (0.75, "Great"), (0.85, "Good")]:
            buy_price = int(private_party * buy_pct)
            sell_price = int(private_party * 0.95)
            costs = 500  # est repair + detailing + fees
            profit = sell_price - buy_price - costs
            roi = round((profit / (buy_price + costs)) * 100, 1) if buy_price > 0 else 0

            profit_color = "green" if profit > 0 else "red"
            flip_table.add_row(
                f"${buy_price:,} ({label})",
                f"${sell_price:,}",
                f"[{profit_color}]${profit:,}[/{profit_color}]",
                f"[{profit_color}]{roi}%[/{profit_color}]",
            )

        console.print(flip_table)

    # Market notes
    notes = data.get("market_notes", "")
    if notes:
        console.print()
        console.print(Panel(notes, title="[bold]Market Notes[/bold]", border_style="yellow"))

    # Confidence & sources
    confidence = data.get("confidence", "unknown")
    sources = data.get("sources", [])
    confidence_color = {"high": "green", "medium": "yellow", "low": "red"}.get(confidence, "dim")
    source_str = ", ".join(sources) if sources else "web search"

    console.print()
    console.print(f"  [bold]Confidence:[/bold] [{confidence_color}]{confidence.upper()}[/{confidence_color}]")
    console.print(f"  [bold]Sources:[/bold] [dim]{source_str}[/dim]")
    console.print()


def _show_value_results_plain(car_desc: str, data: dict) -> None:
    """Plain text value results."""
    print(f"\n=== {car_desc} ===\n")
    print(f"  Trade-In:      ${data.get('trade_in', 0):,}")
    print(f"  Private Party: ${data.get('private_party', 0):,}")
    print(f"  Dealer Retail: ${data.get('dealer_retail', 0):,}")

    notes = data.get("market_notes", "")
    if notes:
        print(f"\n  Notes: {notes}")

    confidence = data.get("confidence", "unknown")
    sources = data.get("sources", [])
    print(f"\n  Confidence: {confidence.upper()}")
    print(f"  Sources: {', '.join(sources) if sources else 'web search'}")


def run_value_cli(args) -> None:
    """Handle the `value` subcommand from argparse."""
    # Parse "2019 Toyota Camry" style positional args
    parts = args.car if args.car else []

    year = args.year
    make = args.make
    model = args.model

    # Try to parse from positional: "2019 Toyota Camry SE"
    if parts and not year:
        try:
            year = int(parts[0])
            if len(parts) >= 2:
                make = parts[1]
            if len(parts) >= 3:
                model = parts[2]
            if len(parts) >= 4:
                args.trim = " ".join(parts[3:])
        except ValueError:
            # Not a year, treat as "Make Model" style
            if len(parts) >= 1:
                make = parts[0]
            if len(parts) >= 2:
                model = parts[1]
            if len(parts) >= 3:
                args.trim = " ".join(parts[2:])

    interactive = not (year and make and model)

    run_value_lookup(
        year=year,
        make=make,
        model=model,
        mileage=args.mileage,
        trim=getattr(args, "trim", None),
        condition=args.condition,
        interactive=interactive,
    )


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def main_loop() -> None:
    """Main interactive CLI loop."""
    show_welcome()

    while True:
        try:
            choice = show_menu()

            if choice == "search":
                config = get_search_config()
                if show_config_summary(config):
                    save_config(config)
                    scores = run_search(config)
                    if scores:
                        show_results(scores)

            elif choice == "value":
                run_value_lookup()

            elif choice == "configure":
                config = get_search_config()
                save_config(config)
                print_msg("[green]Settings saved to Preferences.csv[/green]" if RICH_AVAILABLE else "Settings saved.")

            elif choice == "login":
                run_login()

            elif choice == "history":
                show_history()

            elif choice == "help":
                show_help()

            elif choice == "exit":
                print_msg("[bold blue]Goodbye![/bold blue]" if RICH_AVAILABLE else "Goodbye!")
                break

            else:
                print_msg("[yellow]Invalid choice.[/yellow]" if RICH_AVAILABLE else "Invalid choice.")

        except KeyboardInterrupt:
            print_msg("\n[bold blue]Goodbye![/bold blue]" if RICH_AVAILABLE else "\nGoodbye!")
            break
        except Exception as e:
            logger.error("Error: %s", e)
            print_msg(f"[red]Error: {e}[/red]" if RICH_AVAILABLE else f"Error: {e}")

"""Facebook Marketplace scraper with Playwright session persistence."""

import logging
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Optional

from .models import CarListing, SearchConfig
from .parser import parse_listing_text

logger = logging.getLogger(__name__)

# Try to import Playwright
try:
    from playwright.sync_api import sync_playwright, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

SESSION_DIR = Path(__file__).parent.parent / "data" / "sessions"
SESSION_FILE = SESSION_DIR / "facebook_session.json"
SESSION_MAX_AGE = 86400  # 24 hours

# CSS selectors to find marketplace listing links (tried in order)
LISTING_SELECTORS = [
    "a[href*='/marketplace/item/']",
    "div[role='main'] a[href*='/marketplace/item/']",
    "[data-testid*='marketplace'] a[href*='marketplace/item']",
    "a[href*='marketplace/item']",
]


def is_playwright_available() -> bool:
    return PLAYWRIGHT_AVAILABLE


def has_valid_session() -> bool:
    """Check if a saved Facebook session exists and is fresh enough."""
    if not SESSION_FILE.exists():
        return False
    age = time.time() - SESSION_FILE.stat().st_mtime
    return age < SESSION_MAX_AGE


class FacebookScraper:
    """Scrapes Facebook Marketplace with session persistence."""

    def __init__(self, config: SearchConfig, headless: bool = True):
        self.config = config
        self.headless = headless
        self._progress_callback: Optional[Callable[[str, int], None]] = None

    def set_progress_callback(self, callback: Callable[[str, int], None]) -> None:
        """Set a callback for progress updates: callback(message, percent)."""
        self._progress_callback = callback

    def _progress(self, message: str, percent: int = 0) -> None:
        logger.info(message)
        if self._progress_callback:
            self._progress_callback(message, percent)

    @contextmanager
    def _browser_context(self, timeout: int = 45):
        """Create a Playwright browser context with optional session loading."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

        playwright = None
        browser = None
        context = None

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-extensions",
                    "--no-first-run",
                    "--disable-default-apps",
                ],
                timeout=timeout * 1000,
            )

            context_opts = {
                "user_agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1920, "height": 1080},
                "locale": "en-US",
            }

            if has_valid_session():
                context_opts["storage_state"] = str(SESSION_FILE)
                logger.info("Loaded saved Facebook session")

            context = browser.new_context(**context_opts)
            yield context

        except Exception as e:
            logger.error("Browser automation failed: %s", e)
            raise
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def _save_session(self, context: BrowserContext) -> None:
        """Save the current browser session for reuse."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        logger.info("Saved Facebook session to %s", SESSION_FILE)

    def login_interactive(self) -> bool:
        """Launch a visible browser for the user to log in manually.

        After login is detected, saves the session for future headless runs.
        Returns True if login was successful.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright is not installed")
            return False

        self._progress("Launching browser for Facebook login...", 10)

        playwright = None
        browser = None
        context = None

        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                headless=False,  # Always visible for interactive login
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context_opts = {
                "user_agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1280, "height": 900},
                "locale": "en-US",
            }

            # Load existing session if available
            if has_valid_session():
                context_opts["storage_state"] = str(SESSION_FILE)

            context = browser.new_context(**context_opts)
            page = context.new_page()

            self._progress("Navigating to Facebook login...", 20)
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)

            self._progress("Please log in to Facebook in the browser window...", 30)
            self._progress("Waiting for login to complete (timeout: 5 minutes)...", 30)

            # Wait for the user to log in (detected by URL change or element)
            try:
                page.wait_for_url(
                    "**/facebook.com/?**",
                    timeout=300000,  # 5 minutes
                )
                login_success = True
            except Exception:
                # Check if we're on any page that isn't the login page
                current_url = page.url
                login_success = "/login" not in current_url and "facebook.com" in current_url

            if login_success:
                self._progress("Login detected! Saving session...", 80)
                self._save_session(context)
                self._progress("Session saved successfully!", 100)
                return True
            else:
                self._progress("Login timed out or failed", 100)
                return False

        except Exception as e:
            logger.error("Interactive login failed: %s", e)
            return False
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def scrape(self) -> list[CarListing]:
        """Scrape Facebook Marketplace for car listings.

        Returns a list of CarListing objects. Returns empty list on failure.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright is not installed")
            return []

        url = self.config.build_url()
        self._progress(f"Scraping: {url[:80]}...", 5)

        try:
            with self._browser_context() as context:
                page = context.new_page()
                page.set_default_timeout(30000)

                # Navigate to marketplace
                self._progress("Loading Facebook Marketplace...", 10)
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)

                if not response:
                    self._progress("No response from Facebook", 100)
                    return []

                if response.status != 200:
                    self._progress(f"HTTP {response.status} from Facebook", 100)
                    return []

                self._progress("Page loaded, checking for login requirement...", 15)
                time.sleep(3)  # Wait for JS rendering

                # Check if login is required
                if self._is_login_required(page):
                    if has_valid_session():
                        self._progress("Session expired. Please run --login again.", 100)
                    else:
                        self._progress("Facebook requires login. Run with --login first.", 100)
                    return []

                # Scroll and collect listing hrefs
                self._progress("Scrolling to load listings...", 20)
                hrefs = self._collect_listing_hrefs(page)

                if not hrefs:
                    self._progress("No listings found on page", 100)
                    return []

                self._progress(f"Found {len(hrefs)} listing links, extracting data...", 60)

                # Extract data from each listing
                listings = self._extract_listings(page, hrefs)

                if listings:
                    self._progress(f"Successfully extracted {len(listings)} car listings", 95)
                    # Save session on success (keeps it fresh)
                    self._save_session(context)
                else:
                    self._progress("Could not extract data from listings", 100)

                return listings

        except Exception as e:
            logger.error("Scraping failed: %s", e)
            self._progress(f"Scraping error: {e}", 100)
            return []

    def _is_login_required(self, page: Page) -> bool:
        """Check if Facebook is showing a login page."""
        try:
            page_text = page.inner_text("body")
            lower = page_text.lower()
            return "log in" in lower and ("create new account" in lower or "sign up" in lower)
        except Exception:
            return False

    def _collect_listing_hrefs(self, page: Page) -> set[str]:
        """Scroll the page and collect unique listing hrefs."""
        all_hrefs: set[str] = set()
        previous_count = 0
        no_new_rounds = 0

        for scroll_i in range(self.config.scroll_count):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2)

                for selector in LISTING_SELECTORS:
                    try:
                        links = page.query_selector_all(selector)
                        for link in links:
                            href = link.get_attribute("href")
                            if href and "/marketplace/item/" in href:
                                all_hrefs.add(href)
                    except Exception:
                        continue

                count = len(all_hrefs)
                pct = 20 + int((scroll_i + 1) / self.config.scroll_count * 35)
                self._progress(
                    f"Scroll {scroll_i + 1}/{self.config.scroll_count}: {count} listings",
                    pct,
                )

                if count == previous_count:
                    no_new_rounds += 1
                    if no_new_rounds >= 3:
                        self._progress("No new listings, stopping scroll", pct)
                        break
                else:
                    no_new_rounds = 0

                previous_count = count

                if count >= self.config.max_listings:
                    break

            except Exception as e:
                logger.warning("Scroll %d error: %s", scroll_i + 1, e)
                continue

        return all_hrefs

    def _extract_listings(self, page: Page, hrefs: set[str]) -> list[CarListing]:
        """Extract CarListing objects from collected hrefs."""
        listings: list[CarListing] = []
        seen_signatures: set[str] = set()
        total = min(len(hrefs), self.config.max_listings)

        for i, href in enumerate(list(hrefs)[:total]):
            try:
                if i > 0 and i % 50 == 0:
                    pct = 60 + int(i / total * 30)
                    self._progress(f"Processed {i}/{total} listings...", pct)

                # Find the link element
                link_element = self._find_link_element(page, href)
                if not link_element:
                    continue

                text = link_element.inner_text().strip()
                if not text:
                    continue

                full_url = f"https://www.facebook.com{href}" if href.startswith("/") else href
                listing = parse_listing_text(text, full_url)

                if listing and listing.signature not in seen_signatures:
                    seen_signatures.add(listing.signature)
                    listings.append(listing)

            except Exception as e:
                logger.debug("Error extracting listing: %s", e)
                continue

        return listings

    def _find_link_element(self, page: Page, href: str):
        """Find a link element on the page by its href."""
        try:
            if href.startswith("/"):
                elements = page.query_selector_all(f"a[href='{href}']")
            else:
                path = "/" + "/".join(href.split("/")[3:]) if "facebook.com" in href else href
                elements = page.query_selector_all(f"a[href='{path}']")

            if elements:
                return elements[0]

            # Fallback: match by item ID
            item_id = href.split("/")[-1].split("?")[0]
            for selector in LISTING_SELECTORS:
                try:
                    elements = page.query_selector_all(selector)
                    for elem in elements:
                        elem_href = elem.get_attribute("href")
                        if elem_href and item_id in elem_href:
                            return elem
                except Exception:
                    continue

        except Exception:
            pass

        return None

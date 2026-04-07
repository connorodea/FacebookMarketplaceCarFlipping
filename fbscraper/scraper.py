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
PROFILE_DIR = Path(__file__).parent.parent / "data" / "chrome_profile"
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
    """Check if a persistent Chrome profile with login state exists."""
    # Check persistent profile directory (primary method)
    if PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir()):
        return True
    # Fallback: check legacy session file
    if SESSION_FILE.exists() and SESSION_FILE.stat().st_size > 100:
        age = time.time() - SESSION_FILE.stat().st_mtime
        return age < SESSION_MAX_AGE
    return False


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

    def _cleanup_stale_lock(self) -> None:
        """Check for and remove stale Playwright lock files in PROFILE_DIR."""
        if not PROFILE_DIR.exists():
            return
        for lock_file in PROFILE_DIR.glob("*.lock"):
            try:
                lock_file.unlink()
                logger.info("Removed stale lock file: %s", lock_file)
            except OSError as e:
                logger.debug("Could not remove lock file %s: %s", lock_file, e)
        # Also check for SingletonLock (Chromium-specific)
        singleton_lock = PROFILE_DIR / "SingletonLock"
        if singleton_lock.exists():
            try:
                singleton_lock.unlink()
                logger.info("Removed stale SingletonLock")
            except OSError as e:
                logger.debug("Could not remove SingletonLock: %s", e)

    @contextmanager
    def _browser_context(self, timeout: int = 45):
        """Create a persistent Playwright browser context that retains login state."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

        self._cleanup_stale_lock()

        playwright = None
        context = None

        try:
            playwright = sync_playwright().start()
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)

            context = playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR),
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
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timeout=timeout * 1000,
            )
            logger.info("Launched persistent browser context")
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
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)

            context = playwright.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                headless=False,  # Always visible for interactive login
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )

            page = context.pages[0] if context.pages else context.new_page()

            self._progress("Navigating to Facebook...", 20)
            page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)

            self._progress("Please log in to Facebook in the browser window...", 30)
            self._progress("Waiting for login (you have 5 minutes)...", 30)

            # Poll for login completion instead of using wait_for_url
            # Facebook redirects to many different URLs after login
            login_success = False
            start_time = time.time()
            timeout_seconds = 300  # 5 minutes

            while time.time() - start_time < timeout_seconds:
                try:
                    current_url = page.url
                    # Login is complete when we're no longer on a login/checkpoint page
                    if ("facebook.com" in current_url
                            and "/login" not in current_url
                            and "/checkpoint" not in current_url
                            and "/recover" not in current_url):
                        login_success = True
                        break
                    time.sleep(2)
                except Exception:
                    # Browser may have been closed by user
                    break

            if login_success:
                # Give page a moment to fully load cookies
                time.sleep(2)
                self._progress("Login detected! Saving session...", 80)
                self._save_session(context)
                self._progress("Session saved successfully!", 100)
                return True
            else:
                self._progress("Login timed out or browser was closed", 100)
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
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def scrape(self) -> list[CarListing]:
        """Scrape Facebook Marketplace for car listings.

        Returns a list of CarListing objects. Returns empty list on failure.
        Retries up to 2 times on failure with a 3-second delay.
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright is not installed")
            return []

        url = self.config.build_url()
        max_retries = 2
        last_error: Optional[Exception] = None

        for attempt in range(1 + max_retries):
            if attempt > 0:
                logger.info("Retry attempt %d/%d after 3s delay...", attempt, max_retries)
                self._progress(f"Retrying ({attempt}/{max_retries})...", 2)
                time.sleep(3)

            self._progress(f"Scraping: {url[:80]}...", 5)

            try:
                with self._browser_context() as context:
                    page = context.pages[0] if context.pages else context.new_page()
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
                    else:
                        self._progress("Could not extract data from listings", 100)

                    return listings

            except Exception as e:
                last_error = e
                error_msg = str(e).lower()
                logger.error("Scraping failed (attempt %d): %s", attempt + 1, e)

                # If it's a lock error, clean up locks before retry
                if "lock" in error_msg or "single" in error_msg:
                    logger.info("Detected lock error, cleaning up stale locks...")
                    self._cleanup_stale_lock()

        # All retries exhausted
        self._progress(f"Scraping error after {max_retries + 1} attempts: {last_error}", 100)
        return []

    def _is_login_required(self, page: Page) -> bool:
        """Check if Facebook is showing a login page."""
        try:
            url = page.url.lower()
            if "/login" in url:
                return True
            page_text = page.inner_text("body")[:1000].lower()
            # Only flag as login-required if it looks like an actual login page
            # (not just a "log in" link in the nav of an authenticated page)
            is_login_page = ("log in" in page_text and "create new account" in page_text)
            # If we see user-specific content, we're logged in
            has_user_content = ("marketplace" in page_text or "notification" in page_text
                                or "what's on your mind" in page_text)
            return is_login_page and not has_user_content
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

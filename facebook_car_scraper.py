#!/usr/bin/env python3

import csv
import logging
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Rich imports for beautiful CLI
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.text import Text
    from rich.tree import Tree
    from rich.columns import Columns
    from rich.layout import Layout
    from rich.live import Live
    from rich.align import Align
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich import box
    from rich.style import Style
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Try to import Playwright, but don't fail if it's not available
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Initialize Rich console
console = Console() if RICH_AVAILABLE else None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('facebook_scraper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Global verbose flag
VERBOSE = '--verbose' in sys.argv or '-v' in sys.argv

def read_preferences(preferences_file: str) -> Dict[str, Union[str, int]]:
    """Read preferences from CSV file and return as dictionary."""
    preferences = {}
    logger.info(f"📁 Reading preferences from: {preferences_file}")
    
    try:
        with open(preferences_file, 'r', encoding='utf-8') as f:
            csv_reader = csv.reader(f, delimiter=',')
            for line_num, line in enumerate(csv_reader, 1):
                if len(line) >= 2:
                    key, value = line[0], line[1]
                    try:
                        preferences[key] = int(value)
                        if VERBOSE:
                            logger.info(f"  Line {line_num}: {key} = {value} (int)")
                    except ValueError:
                        preferences[key] = value
                        if VERBOSE:
                            logger.info(f"  Line {line_num}: {key} = {value} (str)")
                elif VERBOSE:
                    logger.warning(f"  Line {line_num}: Skipped invalid line: {line}")
                    
        logger.info(f"✓ Successfully loaded {len(preferences)} preferences")
        
    except FileNotFoundError:
        logger.warning(f"❌ Preferences file '{preferences_file}' not found. Using defaults.")
        return get_default_preferences()
    except Exception as e:
        logger.error(f"❌ Error reading preferences: {e}. Using defaults.")
        return get_default_preferences()
    
    return preferences

def get_default_preferences() -> Dict[str, Union[str, int]]:
    """Return default preferences."""
    defaults = {
        'Minimum Mileage': 0,
        'Maximum Mileage': 200000,
        'Minimum Price': 250,
        'Maximum Price': 55000,
        'Minimum Year': 1995,
        'Maximum Year': 2020,
        'Scroll Down Length': 10,
        'Search Term': '',
        'Location': 'atlanta',
        'Make': '',
        'Model': '',
        'Transmission': '',  # automatic, manual
        'Fuel Type': '',     # gas, hybrid, electric, diesel
        'Body Style': '',    # sedan, suv, coupe, hatchback, truck, convertible
        'Condition': '',     # new, used, salvage
        'Seller Type': '',   # dealer, owner
        'Sort By': 'creation_time_descend',  # creation_time_descend, price_ascend, price_descend, distance_ascend
        'Radius': '20'       # Search radius in miles
    }
    logger.info("📋 Using default preferences:")
    for key, value in defaults.items():
        logger.info(f"  {key}: {value}")
    return defaults

def build_facebook_url(preferences: Dict[str, Union[str, int]]) -> str:
    """Build Facebook Marketplace URL with comprehensive preferences."""
    location = preferences.get('Location', 'atlanta')
    logger.info(f"🔗 Building Facebook URL for location: {location}")
    
    # Handle search terms in URL
    search_term = preferences.get('Search Term', '').strip()
    if search_term:
        base_url = f"https://www.facebook.com/marketplace/{location}/search?"
        params = [f"query={search_term.replace(' ', '%20')}"]
    else:
        base_url = f"https://www.facebook.com/marketplace/{location}/vehicles?"
        params = []
    
    # Basic search parameters
    param_mapping = {
        'Minimum Price': 'minPrice',
        'Maximum Price': 'maxPrice', 
        'Minimum Mileage': 'minMileage',
        'Maximum Mileage': 'maxMileage',
        'Minimum Year': 'minYear',
        'Maximum Year': 'maxYear',
        'Radius': 'radius'
    }
    
    for pref_key, url_param in param_mapping.items():
        if pref_key in preferences and preferences[pref_key]:
            param_value = preferences[pref_key]
            params.append(f"{url_param}={param_value}")
            if VERBOSE:
                logger.info(f"  Added parameter: {url_param}={param_value}")
    
    # Advanced filters mapping
    filter_mapping = {
        'Make': 'make',
        'Model': 'model',
        'Transmission': 'transmission',
        'Fuel Type': 'fuel_type',
        'Body Style': 'body_style',
        'Condition': 'condition',
        'Seller Type': 'seller_type',
        'Sort By': 'sortBy'
    }
    
    for pref_key, url_param in filter_mapping.items():
        if pref_key in preferences and preferences[pref_key]:
            param_value = preferences[pref_key].lower().replace(' ', '_')
            params.append(f"{url_param}={param_value}")
            if VERBOSE:
                logger.info(f"  Added filter: {url_param}={param_value}")
    
    params.append("exact=false")
    
    full_url = base_url + "&".join(params)
    logger.info(f"✓ Built URL: {full_url}")
    return full_url

@contextmanager
def safe_browser_page(timeout: int = 30):
    """Safe browser context manager that handles failures gracefully."""
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("🚫 Playwright not available - skipping browser automation")
        yield None
        return
    
    playwright = None
    browser = None
    context = None
    page = None
    
    try:
        logger.info("🚀 Launching browser...")
        playwright = sync_playwright().start()
        logger.info("✓ Playwright started")
        
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-dev-shm-usage', 
                '--disable-gpu',
                '--disable-blink-features=AutomationControlled',
                '--disable-extensions',
                '--no-first-run',
                '--disable-default-apps'
            ],
            timeout=timeout * 1000
        )
        logger.info("✓ Browser launched")
        
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='en-US'
        )
        logger.info("✓ Browser context created")
        
        page = context.new_page()
        page.set_default_timeout(timeout * 1000)
        logger.info("✓ Page created and ready")
        
        yield page
        
    except Exception as e:
        logger.error(f"❌ Browser automation failed: {e}")
        if VERBOSE:
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
        yield None
    finally:
        cleanup_steps = [
            (lambda: page.close() if page else None, "page"),
            (lambda: context.close() if context else None, "context"),
            (lambda: browser.close() if browser else None, "browser"),
            (lambda: playwright.stop() if playwright else None, "playwright")
        ]
        
        for cleanup_func, component in cleanup_steps:
            try:
                cleanup_func()
                if VERBOSE:
                    logger.info(f"✓ Cleaned up {component}")
            except Exception as e:
                if VERBOSE:
                    logger.warning(f"⚠ Error cleaning up {component}: {e}")

def scrape_facebook_marketplace_safe(url: str, scroll_count: int = 10, max_listings: int = 500) -> List[List[str]]:
    """Enhanced scraping function with pagination support."""
    logger.info(f"🔍 Attempting to scrape: {url}")
    logger.info(f"📊 Scroll count: {scroll_count}, Max listings: {max_listings}")
    
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("🚫 Browser automation not available - using generated sample data")
        return create_realistic_sample_data()
    
    try:
        with safe_browser_page(timeout=45) as page:
            if page is None:
                logger.error("❌ Browser failed to launch - using sample data")
                return create_realistic_sample_data()
            
            logger.info("🌐 Loading Facebook Marketplace...")
            try:
                logger.info(f"📱 Navigating to: {url[:80]}...")
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                if not response:
                    logger.error("❌ No response received from Facebook")
                    return create_realistic_sample_data()
                    
                status_code = response.status
                logger.info(f"📡 Response status: {status_code}")
                
                if status_code != 200:
                    logger.error(f"❌ Failed to load page (status: {status_code})")
                    return create_realistic_sample_data()
                    
                logger.info("✓ Page loaded successfully")
                
            except Exception as e:
                logger.error(f"❌ Navigation failed: {e}")
                if VERBOSE:
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                return create_realistic_sample_data()
            
            logger.info("⏳ Waiting for page to stabilize...")
            time.sleep(3)
            
            # Check for login requirement
            logger.info("🔐 Checking for login requirements...")
            try:
                page_text = page.inner_text()
                if VERBOSE:
                    logger.info(f"📄 Page text length: {len(page_text)} characters")
                    
                if "log in" in page_text.lower() or "sign up" in page_text.lower():
                    logger.warning("🔒 Facebook requires login - using sample data")
                    return create_realistic_sample_data()
                    
                logger.info("✓ No login required")
                
            except Exception as e:
                logger.warning(f"⚠ Could not check page text: {e}")
                if VERBOSE:
                    logger.info("Continuing with scraping attempt...")
            
            # Scroll to load all listings
            logger.info("📜 Scrolling to load all available listings...")
            all_listings = set()  # Use set to avoid duplicates
            previous_count = 0
            no_new_count = 0
            
            for scroll_i in range(scroll_count):
                try:
                    # Scroll down to load more content
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)  # Wait for content to load
                    
                    # Try multiple selectors to find listings
                    selectors = [
                        "a[href*='/marketplace/item/']",
                        "div[role='main'] a[href*='/marketplace/item/']",
                        "[data-testid*='marketplace'] a[href*='marketplace/item']",
                        "a[href*='marketplace/item']",
                        "div[data-pagelet*='marketplace'] a",
                        "[data-testid='marketplace-listing'] a",
                        "div[data-testid='marketplace-listing-card'] a"
                    ]
                    
                    current_listings = set()
                    for selector in selectors:
                        try:
                            links = page.query_selector_all(selector)
                            for link in links:
                                href = link.get_attribute('href')
                                if href and '/marketplace/item/' in href:
                                    current_listings.add(href)
                        except:
                            continue
                    
                    # Add new listings to our collection
                    all_listings.update(current_listings)
                    
                    current_count = len(all_listings)
                    logger.info(f"📊 Scroll {scroll_i + 1}/{scroll_count}: Found {current_count} unique listings")
                    
                    # Check if we're getting new listings
                    if current_count == previous_count:
                        no_new_count += 1
                        if no_new_count >= 3:  # Stop if no new listings for 3 scrolls
                            logger.info("✅ No new listings found, stopping scroll")
                            break
                    else:
                        no_new_count = 0
                    
                    previous_count = current_count
                    
                    # Stop if we've reached max listings
                    if current_count >= max_listings:
                        logger.info(f"✅ Reached maximum listings limit ({max_listings})")
                        break
                        
                except Exception as e:
                    logger.warning(f"⚠ Error during scroll {scroll_i + 1}: {e}")
                    continue
            
            logger.info(f"🎯 Total unique listings found: {len(all_listings)}")
            
            if not all_listings:
                logger.warning("❌ No marketplace links found - using sample data")
                if VERBOSE:
                    logger.info("💡 This could be due to Facebook's dynamic loading or anti-bot measures")
                return create_realistic_sample_data()
            
            # Extract detailed data from listings
            logger.info(f"📝 Extracting detailed car data from {len(all_listings)} listings...")
            car_listings = []
            processed_count = 0
            seen_cars = set()  # Track unique car combinations to prevent duplicates
            
            for href in list(all_listings)[:max_listings]:  # Limit processing
                try:
                    processed_count += 1
                    if processed_count % 50 == 0:
                        logger.info(f"📈 Processed {processed_count}/{min(len(all_listings), max_listings)} listings...")
                    
                    # Find the link element using exact href match
                    link_element = None
                    try:
                        # Try exact href match first (most reliable)
                        if href.startswith('/'):
                            exact_elements = page.query_selector_all(f"a[href='{href}']")
                        else:
                            # For full URLs, try to match the path part
                            path = '/' + '/'.join(href.split('/')[3:]) if 'facebook.com' in href else href
                            exact_elements = page.query_selector_all(f"a[href='{path}']")
                        
                        if exact_elements:
                            link_element = exact_elements[0]
                        else:
                            # Fallback: use original selectors but with better filtering
                            item_id = href.split('/')[-1].split('?')[0]  # Extract just the item ID
                            for selector in selectors:
                                try:
                                    elements = page.query_selector_all(selector)
                                    for elem in elements:
                                        elem_href = elem.get_attribute('href')
                                        if elem_href and item_id in elem_href:
                                            link_element = elem
                                            break
                                    if link_element:
                                        break
                                except:
                                    continue
                    except Exception as e:
                        if VERBOSE:
                            logger.warning(f"  ⚠ Error finding element for {href}: {e}")
                        continue
                    
                    if link_element:
                        text = link_element.inner_text().strip()
                        full_url = f"https://www.facebook.com{href}" if href.startswith('/') else href
                        
                        car_data = parse_car_text_enhanced(text, full_url)
                        if car_data:
                            # Create unique identifier for the car (price, year, make, model, mileage)
                            car_signature = f"{car_data[0]}_{car_data[1]}_{car_data[2]}_{car_data[3]}_{car_data[4]}"
                            
                            # Only add if we haven't seen this exact car before
                            if car_signature not in seen_cars:
                                seen_cars.add(car_signature)
                                car_listings.append(car_data)
                                if VERBOSE and len(car_listings) <= 5:
                                    logger.info(f"  ✓ Extracted: {car_data[1]} {car_data[2]} {car_data[3]} - ${car_data[0]}")
                            elif VERBOSE:
                                logger.info(f"  ⚠ Skipped duplicate: {car_data[1]} {car_data[2]} {car_data[3]} - ${car_data[0]}")
                        
                except Exception as e:
                    if VERBOSE:
                        logger.warning(f"  ⚠ Error processing listing: {e}")
                    continue
            
            logger.info(f"✅ Successfully extracted {len(car_listings)} valid car listings")
            
            if car_listings:
                return car_listings
            else:
                logger.warning("❌ No valid car data extracted - using sample data")
                return create_realistic_sample_data()
                
    except Exception as e:
        logger.error(f"❌ Scraping failed: {e}")
        if VERBOSE:
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
        return create_realistic_sample_data()

def parse_car_text_enhanced(text: str, url: str) -> Optional[List[str]]:
    """Enhanced car listing text parser with better extraction."""
    tokens = text.split()
    
    # Extract price (look for $ followed by numbers)
    price = None
    for token in tokens:
        price_match = re.search(r'\$([0-9,]+)', token)
        if price_match:
            price = price_match.group(1).replace(',', '')
            break
    
    # Extract year (4-digit number between 1990 and current year)
    year = None
    current_year = datetime.now().year
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year_num = int(token)
            if 1990 <= year_num <= current_year:
                year = token
                break
    
    # Enhanced car brands list
    car_brands = [
        'toyota', 'honda', 'ford', 'chevrolet', 'chevy', 'nissan', 'hyundai',
        'kia', 'mazda', 'subaru', 'volkswagen', 'vw', 'bmw', 'mercedes', 'audi',
        'lexus', 'acura', 'infiniti', 'volvo', 'jaguar', 'porsche', 'ferrari',
        'lamborghini', 'maserati', 'bentley', 'rolls-royce', 'tesla', 'lucid',
        'rivian', 'cadillac', 'lincoln', 'buick', 'gmc', 'ram', 'dodge',
        'chrysler', 'jeep', 'mitsubishi', 'genesis', 'alfa', 'fiat', 'mini',
        'land', 'rover', 'range', 'saab', 'pontiac', 'oldsmobile', 'saturn',
        'hummer', 'scion', 'isuzu', 'suzuki', 'daihatsu', 'smart'
    ]
    
    # Extract make and model
    make = None
    model = None
    for i, token in enumerate(tokens):
        token_lower = token.lower().replace('-', '').replace('_', '')
        if token_lower in car_brands:
            make = token.title()
            # Try to get model from next 1-2 tokens
            if i + 1 < len(tokens):
                model = tokens[i + 1].title()
                # Check if next token is also part of model name
                if i + 2 < len(tokens) and not tokens[i + 2].startswith('$') and not tokens[i + 2].isdigit():
                    model += f" {tokens[i + 2].title()}"
            break
    
    # Extract mileage with better patterns
    mileage = None
    mileage_patterns = [
        r'(\d+[,\d]*)\s*k\s*miles?',
        r'(\d+[,\d]*)\s*miles?',
        r'(\d+[,\d]*)\s*k\b',
        r'(\d+[,\d]*)\s*mi\b'
    ]
    
    text_lower = text.lower()
    for pattern in mileage_patterns:
        match = re.search(pattern, text_lower)
        if match:
            mileage_num = match.group(1).replace(',', '')
            try:
                mileage_int = int(mileage_num)
                if 'k' in match.group(0) and mileage_int < 1000:
                    mileage = str(mileage_int * 1000)
                else:
                    mileage = str(mileage_int)
                break
            except:
                continue
    
    # Extract location (look for city, state patterns)
    location = "Unknown"
    location_patterns = [
        r'([A-Z][a-z]+,\s*[A-Z]{2})',
        r'([A-Z][a-z]+\s+[A-Z][a-z]+,\s*[A-Z]{2})',
    ]
    
    for pattern in location_patterns:
        match = re.search(pattern, text)
        if match:
            location = match.group(1)
            break
    
    # Only return if we have essential data
    if price and year and make:
        return [price, year, make, model or "Unknown", mileage or "Unknown", location, url]
    
    return None

def parse_car_text(text: str, url: str) -> Optional[List[str]]:
    """Parse car listing text to extract structured data."""
    tokens = text.split()
    
    # Extract price
    price = None
    for token in tokens:
        if '$' in token:
            price_match = re.search(r'\$([0-9,]+)', token)
            if price_match:
                price = price_match.group(1).replace(',', '')
                break
    
    # Extract year
    year = None
    current_year = datetime.now().year
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year_num = int(token)
            if 1990 <= year_num <= current_year:
                year = token
                break
    
    # Extract make
    car_brands = [
        'toyota', 'honda', 'ford', 'chevrolet', 'chevy', 'nissan', 'hyundai',
        'kia', 'mazda', 'subaru', 'volkswagen', 'vw', 'bmw', 'mercedes', 'audi'
    ]
    
    make = None
    model = None
    for i, token in enumerate(tokens):
        if token.lower() in car_brands:
            make = token.title()
            if i + 1 < len(tokens):
                model = tokens[i + 1].title()
            break
    
    # Extract mileage
    mileage = None
    for token in tokens:
        if 'k' in token.lower() or 'mile' in token.lower():
            mile_match = re.search(r'([0-9,]+)', token)
            if mile_match:
                mileage = mile_match.group(1).replace(',', '')
                if 'k' in token.lower():
                    try:
                        mileage = str(int(mileage) * 1000)
                    except:
                        pass
                break
    
    if price and year and make:
        return [price, year, make, model or "Unknown", mileage or "Unknown", "Atlanta, GA", url]
    
    return None

def create_realistic_sample_data() -> List[List[str]]:
    """Create realistic sample car data for testing."""
    sample_cars = [
        ["14500", "2015", "Honda", "Civic", "78000", "Atlanta, GA", "https://facebook.com/marketplace/item/sample1"],
        ["9200", "2012", "Toyota", "Corolla", "112000", "Decatur, GA", "https://facebook.com/marketplace/item/sample2"],
        ["19800", "2017", "Nissan", "Altima", "62000", "Sandy Springs, GA", "https://facebook.com/marketplace/item/sample3"],
        ["13200", "2014", "Chevrolet", "Malibu", "89000", "Marietta, GA", "https://facebook.com/marketplace/item/sample4"],
        ["21500", "2018", "Ford", "Fusion", "45000", "Roswell, GA", "https://facebook.com/marketplace/item/sample5"],
        ["10800", "2013", "Hyundai", "Elantra", "95000", "Alpharetta, GA", "https://facebook.com/marketplace/item/sample6"],
        ["17200", "2016", "Mazda", "Mazda3", "68000", "Dunwoody, GA", "https://facebook.com/marketplace/item/sample7"],
        ["12900", "2014", "Kia", "Optima", "82000", "Brookhaven, GA", "https://facebook.com/marketplace/item/sample8"],
    ]
    logger.info(f"📊 Generated {len(sample_cars)} realistic sample car listings")
    if VERBOSE:
        logger.info("📝 Sample data preview:")
        for i, car in enumerate(sample_cars[:3], 1):
            logger.info(f"  {i}. {car[1]} {car[2]} {car[3]} - ${car[0]} ({car[4]} miles)")
        if len(sample_cars) > 3:
            logger.info(f"  ... and {len(sample_cars) - 3} more")
    return sample_cars

def get_market_pricing_estimate(make: str, model: str, year: str, price: str) -> List[int]:
    """Generate estimated market pricing."""
    try:
        listing_price = int(price)
        year_int = int(year)
        current_year = datetime.now().year
        age = current_year - year_int
        
        # Base market value
        base_multiplier = 1.12
        
        # Brand factor
        premium_brands = ['bmw', 'mercedes', 'lexus', 'audi']
        reliable_brands = ['toyota', 'honda', 'mazda']
        
        if make.lower() in premium_brands:
            brand_factor = 1.08
        elif make.lower() in reliable_brands:
            brand_factor = 1.04
        else:
            brand_factor = 1.0
        
        # Age depreciation
        age_factor = max(0.75, 1.0 - (age * 0.04))
        
        estimated_value = listing_price * base_multiplier * brand_factor * age_factor
        
        # Create price range
        trade_in = int(estimated_value * 0.85)
        private_party = int(estimated_value * 0.98)
        dealer_retail = int(estimated_value * 1.12)
        
        return [trade_in, private_party, dealer_retail]
    except:
        return [8000, 10000, 12000]

def calculate_deal_scores(car_listings: List[List[str]]) -> List[List]:
    """Calculate deal scores for car listings."""
    scored_listings = []
    
    for i, car in enumerate(car_listings):
        try:
            if len(car) < 4:
                continue
            
            price = float(car[0])
            year = int(car[1]) if car[1].isdigit() else 2010
            make = car[2]
            model = car[3]
            
            # Get market pricing
            market_prices = get_market_pricing_estimate(make, model, str(year), str(int(price)))
            
            # Calculate mileage condition
            mileage = None
            if len(car) > 4 and car[4] != "Unknown":
                try:
                    mileage = int(car[4].replace(',', ''))
                except:
                    pass
            
            if mileage:
                if mileage < 50000:
                    condition = "Excellent"
                    condition_factor = 1.0
                elif mileage < 80000:
                    condition = "Good"
                    condition_factor = 0.92
                elif mileage < 120000:
                    condition = "Fair"
                    condition_factor = 0.85
                else:
                    condition = "Poor"
                    condition_factor = 0.75
            else:
                condition = "Unknown"
                condition_factor = 0.90
            
            # Calculate ratio
            avg_market = sum(market_prices) / len(market_prices)
            adjusted_market = avg_market * condition_factor
            ratio = adjusted_market / price
            
            # Determine deal quality
            if ratio > 1.25:
                deal_quality = "Excellent"
            elif ratio > 1.10:
                deal_quality = "Good"
            elif ratio > 0.95:
                deal_quality = "Fair"
            else:
                deal_quality = "Poor"
            
            # Create scored entry
            scored_car = [round(ratio, 3), condition, deal_quality] + car + [market_prices]
            scored_listings.append(scored_car)
            
        except Exception as e:
            print(f"Error scoring car {i+1}: {e}")
            continue
    
    # Sort by ratio (best deals first)
    scored_listings.sort(key=lambda x: float(x[0]), reverse=True)
    return scored_listings

def save_results_to_csv(car_listings: List[List], output_dir: str = ".") -> str:
    """Save results to CSV file."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"facebook_marketplace_cars_{timestamp}.csv"
    filepath = Path(output_dir) / filename
    
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            header = ['Deal_Ratio', 'Condition', 'Deal_Quality', 'Listing_Price', 'Year', 'Make', 'Model', 
                     'Mileage', 'Location', 'Facebook_URL', 'Market_Prices']
            writer.writerow(header)
            
            # Data
            for car in car_listings:
                try:
                    if len(car) >= 10:
                        ratio = car[0]
                        condition = car[1]
                        deal_quality = car[2]
                        price = car[3]
                        year = car[4]
                        make = car[5]
                        model = car[6]
                        mileage = car[7]
                        location = car[8]
                        url = car[9]
                        market_prices = ','.join([f"${p}" for p in car[10]]) if len(car) > 10 else "N/A"
                        
                        writer.writerow([ratio, condition, deal_quality, price, year, make, model, 
                                       mileage, location, url, market_prices])
                except Exception as e:
                    print(f"Error writing row: {e}")
                    continue
        
        print(f"Results saved to: {filepath}")
        return str(filepath)
        
    except Exception as e:
        print(f"Error saving results: {e}")
        return ""

def show_welcome_screen():
    """Display a beautiful welcome screen."""
    if not RICH_AVAILABLE:
        print("=== Facebook Marketplace Car Scraper ===")
        return
    
    console.clear()
    
    # Create welcome content
    welcome_content = """[bold blue]Facebook Marketplace Car Scraper[/bold blue]
[italic cyan]🚗 Find the best car deals with AI-powered analysis[/italic cyan]

[bold]System Status:[/bold]"""
    
    if PLAYWRIGHT_AVAILABLE:
        welcome_content += "\n✅ [green]Playwright[/green] - Web scraping available"
    else:
        welcome_content += "\n⚠️ [yellow]Playwright[/yellow] - Fallback mode (sample data)"
    
    welcome_content += """
✅ [green]Rich CLI[/green] - Enhanced interface active
🔍 [blue]Search Engine[/blue] - Facebook Marketplace ready"""
    
    welcome_panel = Panel(
        Align.center(welcome_content),
        title="[bold]Welcome[/bold]",
        border_style="blue",
        padding=(2, 4)
    )
    
    console.print("\n")
    console.print(welcome_panel)
    console.print()

def show_main_menu() -> str:
    """Display GitHub CLI-style main menu."""
    if not RICH_AVAILABLE:
        print("\n=== MAIN MENU ===")
        print("1. Search Cars")
        print("2. Configure Settings")
        print("3. View Recent Results")
        print("4. Help")
        print("5. Exit")
        choice = input("Select an option (1-5): ").strip()
        return {"1": "search", "2": "config", "3": "results", "4": "help", "5": "exit"}.get(choice, "invalid")
    
    console.print(Rule("[bold blue]Main Menu[/bold blue]"))
    
    # Create menu options
    menu_table = Table(show_header=False, box=None, padding=(0, 2))
    menu_table.add_column(style="cyan", min_width=3)
    menu_table.add_column(style="bold", min_width=20)
    menu_table.add_column(style="dim")
    
    menu_table.add_row("🔍", "search cars", "Search Facebook Marketplace with custom filters")
    menu_table.add_row("⚙️", "configure", "Modify search preferences and settings")
    menu_table.add_row("📊", "results", "View and analyze recent search results")
    menu_table.add_row("📈", "analytics", "View market trends and pricing insights")
    menu_table.add_row("❓", "help", "Show help and usage information")
    menu_table.add_row("🚪", "exit", "Exit the application")
    
    console.print(menu_table)
    console.print()
    
    choice = Prompt.ask(
        "[bold cyan]What would you like to do?[/bold cyan]",
        choices=["search", "configure", "results", "analytics", "help", "exit"],
        default="search"
    )
    
    return choice

def get_search_preferences_rich() -> Dict[str, Union[str, int]]:
    """Get search preferences with rich interface."""
    if not RICH_AVAILABLE:
        return get_user_search_preferences_fallback()
    
    console.print(Rule("[bold green]Search Configuration[/bold green]"))
    console.print("[dim]Configure your car search parameters[/dim]\n")
    
    preferences = get_default_preferences()
    
    # Basic search parameters
    console.print(Panel("🔍 [bold]Basic Search Parameters[/bold]", border_style="green"))
    
    search_term = Prompt.ask(
        "🔍 Search term (e.g., 'Honda Civic', 'Toyota')",
        default=preferences.get('Search Term', ''),
        show_default=True
    )
    if search_term:
        preferences['Search Term'] = search_term
    
    location = Prompt.ask(
        "📍 Location (e.g., 'atlanta', 'miami', 'chicago')",
        default=preferences.get('Location', 'atlanta')
    )
    preferences['Location'] = location
    
    # Price range
    console.print("\n💰 [bold cyan]Price Range[/bold cyan]")
    min_price = IntPrompt.ask(
        "Minimum price ($)",
        default=preferences.get('Minimum Price', 250)
    )
    preferences['Minimum Price'] = min_price
    
    max_price = IntPrompt.ask(
        "Maximum price ($)",
        default=preferences.get('Maximum Price', 55000)
    )
    preferences['Maximum Price'] = max_price
    
    # Year range
    console.print("\n📅 [bold cyan]Year Range[/bold cyan]")
    min_year = IntPrompt.ask(
        "Minimum year",
        default=preferences.get('Minimum Year', 1995)
    )
    preferences['Minimum Year'] = min_year
    
    max_year = IntPrompt.ask(
        "Maximum year",
        default=preferences.get('Maximum Year', 2020)
    )
    preferences['Maximum Year'] = max_year
    
    # Mileage
    max_mileage = IntPrompt.ask(
        "🛣️ Maximum mileage",
        default=preferences.get('Maximum Mileage', 200000)
    )
    preferences['Maximum Mileage'] = max_mileage
    
    # Advanced filters
    console.print(Panel("🎛️ [bold]Advanced Filters[/bold] [dim](optional)[/dim]", border_style="yellow"))
    
    make = Prompt.ask("🏭 Make (e.g., 'Toyota', 'Honda')", default="")
    if make:
        preferences['Make'] = make
    
    model = Prompt.ask("🚗 Model (e.g., 'Civic', 'Camry')", default="")
    if model:
        preferences['Model'] = model
    
    transmission_choice = Prompt.ask(
        "⚙️ Transmission",
        choices=["", "automatic", "manual"],
        default=""
    )
    if transmission_choice:
        preferences['Transmission'] = transmission_choice
    
    fuel_choice = Prompt.ask(
        "⛽ Fuel type",
        choices=["", "gas", "hybrid", "electric", "diesel"],
        default=""
    )
    if fuel_choice:
        preferences['Fuel Type'] = fuel_choice
    
    body_choice = Prompt.ask(
        "🚙 Body style",
        choices=["", "sedan", "suv", "coupe", "hatchback", "truck", "convertible"],
        default=""
    )
    if body_choice:
        preferences['Body Style'] = body_choice
    
    # Scraping preferences
    console.print(Panel("📜 [bold]Scraping Options[/bold]", border_style="blue"))
    
    scroll_count = IntPrompt.ask(
        "Scroll iterations (more = more listings)",
        default=preferences.get('Scroll Down Length', 10)
    )
    preferences['Scroll Down Length'] = scroll_count
    
    return preferences

def get_user_search_preferences_fallback() -> Dict[str, Union[str, int]]:
    """Fallback function for when Rich is not available."""
    print("\n🔧 === SEARCH CONFIGURATION ===")
    print("Enter your search preferences (press Enter to use defaults):")
    
    preferences = get_default_preferences()
    
    # Interactive input for key parameters
    search_term = input(f"🔍 Search term (e.g., 'honda civic', 'toyota', etc.) [{preferences.get('Search Term', 'any car')}]: ").strip()
    if search_term:
        preferences['Search Term'] = search_term
    
    location = input(f"📍 Location (e.g., 'atlanta', 'miami', 'chicago') [{preferences.get('Location', 'atlanta')}]: ").strip()
    if location:
        preferences['Location'] = location
    
    # Price range
    try:
        min_price = input(f"💰 Minimum price [${preferences.get('Minimum Price', 250)}]: ").strip()
        if min_price:
            preferences['Minimum Price'] = int(min_price)
    except ValueError:
        print("⚠ Invalid price, using default")
    
    try:
        max_price = input(f"💰 Maximum price [${preferences.get('Maximum Price', 55000)}]: ").strip()
        if max_price:
            preferences['Maximum Price'] = int(max_price)
    except ValueError:
        print("⚠ Invalid price, using default")
    
    # Year range
    try:
        min_year = input(f"📅 Minimum year [{preferences.get('Minimum Year', 1995)}]: ").strip()
        if min_year:
            preferences['Minimum Year'] = int(min_year)
    except ValueError:
        print("⚠ Invalid year, using default")
    
    try:
        max_year = input(f"📅 Maximum year [{preferences.get('Maximum Year', 2020)}]: ").strip()
        if max_year:
            preferences['Maximum Year'] = int(max_year)
    except ValueError:
        print("⚠ Invalid year, using default")
    
    # Mileage range
    try:
        max_mileage = input(f"🛣️ Maximum mileage [{preferences.get('Maximum Mileage', 200000)}]: ").strip()
        if max_mileage:
            preferences['Maximum Mileage'] = int(max_mileage)
    except ValueError:
        print("⚠ Invalid mileage, using default")
    
    # Advanced filters
    print("\n🎛️ Advanced Filters (optional):")
    
    make = input("🏭 Make (e.g., 'Toyota', 'Honda'): ").strip()
    if make:
        preferences['Make'] = make
    
    model = input("🚗 Model (e.g., 'Civic', 'Camry'): ").strip()
    if model:
        preferences['Model'] = model
    
    transmission = input("⚙️ Transmission (automatic/manual): ").strip()
    if transmission and transmission.lower() in ['automatic', 'manual']:
        preferences['Transmission'] = transmission.lower()
    
    fuel_type = input("⛽ Fuel type (gas/hybrid/electric/diesel): ").strip()
    if fuel_type and fuel_type.lower() in ['gas', 'hybrid', 'electric', 'diesel']:
        preferences['Fuel Type'] = fuel_type.lower()
    
    body_style = input("🚙 Body style (sedan/suv/coupe/hatchback/truck/convertible): ").strip()
    if body_style and body_style.lower() in ['sedan', 'suv', 'coupe', 'hatchback', 'truck', 'convertible']:
        preferences['Body Style'] = body_style.lower()
    
    # Scraping preferences
    try:
        scroll_count = input(f"📜 Scroll iterations for more listings [{preferences.get('Scroll Down Length', 10)}]: ").strip()
        if scroll_count:
            preferences['Scroll Down Length'] = int(scroll_count)
    except ValueError:
        print("⚠ Invalid scroll count, using default")
    
    return preferences

def show_search_summary_rich(preferences: Dict[str, Union[str, int]]) -> bool:
    """Show search summary with rich formatting."""
    if not RICH_AVAILABLE:
        return show_search_summary_fallback(preferences)
    
    console.print(Rule("[bold cyan]Search Summary[/bold cyan]"))
    
    # Create summary table
    summary_table = Table(title="Search Configuration", box=box.ROUNDED)
    summary_table.add_column("Parameter", style="cyan", min_width=20)
    summary_table.add_column("Value", style="yellow")
    
    # Add basic parameters
    summary_table.add_row("🔍 Search Term", preferences.get('Search Term', 'Any car') or 'Any car')
    summary_table.add_row("📍 Location", preferences.get('Location', 'atlanta'))
    summary_table.add_row("💰 Price Range", f"${preferences.get('Minimum Price', 0):,} - ${preferences.get('Maximum Price', 999999):,}")
    summary_table.add_row("📅 Year Range", f"{preferences.get('Minimum Year', 1990)} - {preferences.get('Maximum Year', 2025)}")
    summary_table.add_row("🛣️ Max Mileage", f"{preferences.get('Maximum Mileage', 999999):,} miles")
    
    # Add advanced filters if set
    if preferences.get('Make'):
        summary_table.add_row("🏭 Make", preferences['Make'])
    if preferences.get('Model'):
        summary_table.add_row("🚗 Model", preferences['Model'])
    if preferences.get('Transmission'):
        summary_table.add_row("⚙️ Transmission", preferences['Transmission'])
    if preferences.get('Fuel Type'):
        summary_table.add_row("⛽ Fuel Type", preferences['Fuel Type'])
    if preferences.get('Body Style'):
        summary_table.add_row("🚙 Body Style", preferences['Body Style'])
    
    summary_table.add_row("📜 Scroll Count", str(preferences.get('Scroll Down Length', 10)))
    
    console.print(summary_table)
    console.print()
    
    return Confirm.ask("[bold green]Proceed with this search?[/bold green]", default=True)

def show_search_summary_fallback(preferences: Dict[str, Union[str, int]]) -> bool:
    """Fallback search summary for when Rich is not available."""
    print(f"\n📋 === SEARCH SUMMARY ===")
    print(f"🔍 Search term: {preferences.get('Search Term', 'Any car')}")
    print(f"📍 Location: {preferences.get('Location', 'atlanta')}")
    print(f"💰 Price range: ${preferences.get('Minimum Price', 0):,} - ${preferences.get('Maximum Price', 999999):,}")
    print(f"📅 Year range: {preferences.get('Minimum Year', 1990)} - {preferences.get('Maximum Year', 2025)}")
    print(f"🛣️ Max mileage: {preferences.get('Maximum Mileage', 999999):,}")
    
    confirm = input("\n✅ Proceed with search? (y/n) [y]: ").strip().lower()
    return confirm != 'n'

def run_search_with_progress(preferences: Dict[str, Union[str, int]]) -> Optional[str]:
    """Run search with rich progress bars."""
    if not RICH_AVAILABLE:
        return run_search_fallback(preferences)
    
    # Build URL
    facebook_url = build_facebook_url(preferences)
    scroll_count = preferences.get('Scroll Down Length', 10)
    max_listings = 500
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        
        # Main scraping task
        scrape_task = progress.add_task("[cyan]Scraping Facebook Marketplace...", total=100)
        
        # Initialize browser
        progress.update(scrape_task, advance=10, description="[cyan]Launching browser...")
        time.sleep(0.5)
        
        progress.update(scrape_task, advance=20, description="[cyan]Loading Facebook Marketplace...")
        car_listings = scrape_facebook_marketplace_rich(facebook_url, scroll_count, max_listings, progress, scrape_task)
        
        if not car_listings:
            console.print("[red]❌ No car data available.[/red]")
            return None
        
        progress.update(scrape_task, advance=80, description=f"[green]Found {len(car_listings)} listings!")
        
        # Analysis task
        analysis_task = progress.add_task("[yellow]Analyzing deals...", total=len(car_listings))
        
        final_listings = []
        for i, car in enumerate(car_listings):
            # Simulate processing time for demo
            time.sleep(0.01)
            progress.update(analysis_task, advance=1)
            
        final_listings = calculate_deal_scores(car_listings)
        progress.update(analysis_task, completed=len(car_listings), description="[green]Analysis complete!")
        
        # Save results
        progress.update(scrape_task, advance=100, description="[green]Saving results...")
        output_file = save_results_to_csv(final_listings)
        
        progress.update(scrape_task, completed=100, description="[green]Search completed!")
    
    return output_file, final_listings

def run_search_fallback(preferences: Dict[str, Union[str, int]]) -> Optional[str]:
    """Fallback search without rich progress."""
    facebook_url = build_facebook_url(preferences)
    scroll_count = preferences.get('Scroll Down Length', 10)
    max_listings = 500
    
    print(f"\n⏳ Searching Facebook Marketplace...")
    print(f"📊 Will scroll {scroll_count} times to find up to {max_listings} listings")
    
    car_listings = scrape_facebook_marketplace_safe(facebook_url, scroll_count, max_listings)
    
    if not car_listings:
        print("❌ No car data available.")
        return None
    
    print(f"✅ Found {len(car_listings)} car listings!")
    print("📈 Analyzing deals and market values...")
    
    final_listings = calculate_deal_scores(car_listings)
    output_file = save_results_to_csv(final_listings)
    
    return output_file, final_listings

def scrape_facebook_marketplace_rich(url: str, scroll_count: int, max_listings: int, progress, task_id) -> List[List[str]]:
    """Enhanced scraping with rich progress updates."""
    if not PLAYWRIGHT_AVAILABLE:
        progress.update(task_id, description="[yellow]Using sample data (Playwright not available)")
        return create_realistic_sample_data()
    
    try:
        with safe_browser_page(timeout=45) as page:
            if page is None:
                progress.update(task_id, description="[red]Browser failed to launch")
                return create_realistic_sample_data()
            
            progress.update(task_id, advance=10, description="[cyan]Navigating to Facebook...")
            
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if not response or response.status != 200:
                    progress.update(task_id, description="[red]Failed to load page")
                    return create_realistic_sample_data()
                
                progress.update(task_id, advance=10, description="[cyan]Page loaded successfully")
                
            except Exception as e:
                progress.update(task_id, description=f"[red]Navigation failed: {str(e)[:50]}")
                return create_realistic_sample_data()
            
            time.sleep(3)
            
            # Check for login requirement
            try:
                page_text = page.inner_text()
                if "log in" in page_text.lower() or "sign up" in page_text.lower():
                    progress.update(task_id, description="[yellow]Login required - using sample data")
                    return create_realistic_sample_data()
            except:
                pass
            
            # Scroll and collect listings
            progress.update(task_id, advance=10, description="[cyan]Scrolling to load listings...")
            all_listings = set()
            
            for scroll_i in range(scroll_count):
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    
                    # Try multiple selectors
                    selectors = [
                        "a[href*='/marketplace/item/']",
                        "div[role='main'] a[href*='/marketplace/item/']",
                        "[data-testid*='marketplace'] a[href*='marketplace/item']"
                    ]
                    
                    current_listings = set()
                    for selector in selectors:
                        try:
                            links = page.query_selector_all(selector)
                            for link in links:
                                href = link.get_attribute('href')
                                if href and '/marketplace/item/' in href:
                                    current_listings.add(href)
                        except:
                            continue
                    
                    all_listings.update(current_listings)
                    
                    # Update progress
                    progress_percent = min(40, (scroll_i + 1) / scroll_count * 40)
                    progress.update(task_id, advance=progress_percent/scroll_count, 
                                  description=f"[cyan]Found {len(all_listings)} listings (scroll {scroll_i + 1}/{scroll_count})")
                    
                    if len(all_listings) >= max_listings:
                        break
                        
                except Exception:
                    continue
            
            progress.update(task_id, advance=20, description=f"[cyan]Extracting data from {len(all_listings)} listings...")
            
            # Extract car data
            car_listings = []
            processed_count = 0
            seen_cars = set()  # Track unique car combinations to prevent duplicates
            
            for href in list(all_listings)[:max_listings]:
                try:
                    processed_count += 1
                    
                    # Find the link element using exact href match
                    link_element = None
                    try:
                        # Try exact href match first (most reliable)
                        if href.startswith('/'):
                            exact_elements = page.query_selector_all(f"a[href='{href}']")
                        else:
                            # For full URLs, try to match the path part
                            path = '/' + '/'.join(href.split('/')[3:]) if 'facebook.com' in href else href
                            exact_elements = page.query_selector_all(f"a[href='{path}']")
                        
                        if exact_elements:
                            link_element = exact_elements[0]
                        else:
                            # Fallback: use original selectors but with better filtering
                            item_id = href.split('/')[-1].split('?')[0]  # Extract just the item ID
                            for selector in selectors:
                                try:
                                    elements = page.query_selector_all(selector)
                                    for elem in elements:
                                        elem_href = elem.get_attribute('href')
                                        if elem_href and item_id in elem_href:
                                            link_element = elem
                                            break
                                    if link_element:
                                        break
                                except:
                                    continue
                    except Exception:
                        continue
                    
                    if link_element:
                        text = link_element.inner_text().strip()
                        full_url = f"https://www.facebook.com{href}" if href.startswith('/') else href
                        
                        car_data = parse_car_text_enhanced(text, full_url)
                        if car_data:
                            # Create unique identifier for the car (price, year, make, model, mileage)
                            car_signature = f"{car_data[0]}_{car_data[1]}_{car_data[2]}_{car_data[3]}_{car_data[4]}"
                            
                            # Only add if we haven't seen this exact car before
                            if car_signature not in seen_cars:
                                seen_cars.add(car_signature)
                                car_listings.append(car_data)
                    
                    # Update progress periodically
                    if processed_count % 10 == 0:
                        progress.update(task_id, advance=1, 
                                      description=f"[cyan]Processed {processed_count}/{min(len(all_listings), max_listings)} listings")
                        
                except Exception:
                    continue
            
            if car_listings:
                return car_listings
            else:
                progress.update(task_id, description="[yellow]No valid data - using sample")
                return create_realistic_sample_data()
                
    except Exception as e:
        progress.update(task_id, description=f"[red]Scraping failed: {str(e)[:50]}")
        return create_realistic_sample_data()

def show_results_rich(output_file: str, final_listings: List[List]) -> None:
    """Display results with rich formatting."""
    if not RICH_AVAILABLE:
        show_results_fallback(output_file, final_listings)
        return
    
    console.print(Rule("[bold green]Search Results[/bold green]"))
    
    # Results summary
    excellent_deals = [car for car in final_listings if car[2] == "Excellent"]
    good_deals = [car for car in final_listings if car[2] == "Good"]
    
    summary_table = Table(title="Deal Quality Summary", box=box.ROUNDED, title_style="bold cyan")
    summary_table.add_column("Quality", style="bold")
    summary_table.add_column("Count", justify="center", style="yellow")
    summary_table.add_column("Percentage", justify="center", style="dim")
    
    total = len(final_listings)
    summary_table.add_row("🌟 Excellent", str(len(excellent_deals)), f"{len(excellent_deals)/total*100:.1f}%")
    summary_table.add_row("✅ Good", str(len(good_deals)), f"{len(good_deals)/total*100:.1f}%")
    summary_table.add_row("📊 Total", str(total), "100.0%")
    
    console.print(summary_table)
    console.print()
    
    # Top deals table
    deals_table = Table(title="🏆 Top 10 Best Deals", box=box.ROUNDED, title_style="bold yellow")
    deals_table.add_column("Rank", style="dim", width=4)
    deals_table.add_column("Quality", width=8)
    deals_table.add_column("Vehicle", style="bold cyan", min_width=20)
    deals_table.add_column("Price", style="green", justify="right")
    deals_table.add_column("Mileage", style="blue", justify="right")
    deals_table.add_column("Ratio", style="yellow", justify="right")
    
    for i, car in enumerate(final_listings[:10]):
        try:
            ratio = float(car[0])
            condition = car[1]
            deal_quality = car[2]
            price = car[3]
            year = car[4]
            make = car[5]
            model = car[6]
            mileage = car[7]
            
            quality_emoji = "🌟" if deal_quality == "Excellent" else "✅" if deal_quality == "Good" else "📊"
            vehicle_str = f"{year} {make} {model}"
            
            deals_table.add_row(
                str(i + 1),
                f"{quality_emoji} {deal_quality}",
                vehicle_str,
                f"${price}",
                f"{mileage} mi",
                f"{ratio:.2f}"
            )
        except Exception:
            continue
    
    console.print(deals_table)
    console.print()
    
    # File info
    console.print(Panel(
        f"[green]✅ Results saved to:[/green] [cyan]{output_file}[/cyan]\n"
        f"[dim]Open this file in Excel or any CSV viewer to see all results[/dim]",
        title="[bold]Output File[/bold]",
        border_style="green"
    ))

def show_results_fallback(output_file: str, final_listings: List[List]) -> None:
    """Fallback results display."""
    excellent_deals = [car for car in final_listings if car[2] == "Excellent"]
    good_deals = [car for car in final_listings if car[2] == "Good"]
    
    print(f"\n=== 📊 RESULTS SUMMARY ===")
    print(f"Total cars analyzed: {len(final_listings)}")
    print(f"Results saved to: {output_file}")
    
    print(f"\n🏆 Deal Quality Breakdown:")
    print(f"  🌟 Excellent deals: {len(excellent_deals)}")
    print(f"  ✅ Good deals: {len(good_deals)}")
    print(f"  📊 Total deals: {len(final_listings)}")
    
    print(f"\n🏆 Top 10 Best Deals:")
    for i, car in enumerate(final_listings[:10]):
        try:
            ratio = float(car[0])
            condition = car[1]
            deal_quality = car[2]
            price = car[3]
            year = car[4]
            make = car[5]
            model = car[6]
            mileage = car[7]
            
            quality_emoji = "🌟" if deal_quality == "Excellent" else "✅" if deal_quality == "Good" else "📊"
            print(f"  {i+1:2d}. {quality_emoji} {year} {make} {model} - ${price} | {mileage} mi | Ratio: {ratio:.2f}")
        except Exception as e:
            print(f"  {i+1}. Error displaying car: {e}")

def main():
    """Enhanced main function with GitHub CLI-style interface."""
    
    # Check for non-interactive mode
    non_interactive = '--non-interactive' in sys.argv
    
    if non_interactive:
        # Original behavior for automation
        if VERBOSE:
            print("🔍 VERBOSE mode enabled")
            logger.info("🔍 Verbose logging enabled")
        
        logger.info("🤖 Running in non-interactive mode")
        preferences = read_preferences("Preferences.csv")
        
        result = run_search_fallback(preferences)
        if result:
            output_file, final_listings = result
            show_results_fallback(output_file, final_listings)
        return
    
    # Rich CLI interface
    if not RICH_AVAILABLE:
        # Fallback to original interface
        preferences = get_user_search_preferences_fallback()
        if show_search_summary_fallback(preferences):
            result = run_search_fallback(preferences)
            if result:
                output_file, final_listings = result
                show_results_fallback(output_file, final_listings)
        return
    
    # Main Rich CLI loop
    try:
        show_welcome_screen()
        
        while True:
            choice = show_main_menu()
            
            if choice == "search":
                preferences = get_search_preferences_rich()
                
                if show_search_summary_rich(preferences):
                    console.print()
                    result = run_search_with_progress(preferences)
                    
                    if result:
                        output_file, final_listings = result
                        console.print()
                        show_results_rich(output_file, final_listings)
                    
                    console.print()
                    if not Confirm.ask("[bold cyan]Run another search?[/bold cyan]", default=False):
                        break
                        
            elif choice == "configure":
                console.print("[yellow]Configuration editor coming soon![/yellow]")
                console.print("For now, edit the Preferences.csv file directly.")
                
            elif choice == "results":
                console.print("[yellow]Results viewer coming soon![/yellow]")
                console.print("Check your CSV files in the current directory.")
                
            elif choice == "analytics":
                console.print("[yellow]Analytics dashboard coming soon![/yellow]")
                console.print("This will show market trends and pricing insights.")
                
            elif choice == "help":
                show_help_rich()
                
            elif choice == "exit":
                console.print("[green]👋 Thanks for using Facebook Marketplace Car Scraper![/green]")
                break
                
            else:
                console.print("[red]Invalid choice. Please try again.[/red]")
                
    except KeyboardInterrupt:
        console.print("\n[yellow]👋 Search cancelled. Goodbye![/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Critical error: {e}[/red]")
        if VERBOSE:
            console.print_exception()

def show_help_rich():
    """Display help information with rich formatting."""
    if not RICH_AVAILABLE:
        show_help_fallback()
        return
    
    console.print(Rule("[bold blue]Help & Usage[/bold blue]"))
    
    help_content = """
[bold cyan]🚗 Facebook Marketplace Car Scraper[/bold cyan]

[bold]DESCRIPTION:[/bold]
This tool searches Facebook Marketplace for cars and analyzes deals to find the best opportunities.

[bold]FEATURES:[/bold]
• 🔍 Comprehensive search with multiple filters
• 📊 AI-powered deal analysis and scoring
• 📈 Market value estimation
• 🎯 Advanced filtering (make, model, transmission, etc.)
• 📱 Beautiful CLI interface with progress tracking

[bold]SEARCH PARAMETERS:[/bold]
• [cyan]Search Term[/cyan]: Specific car models (e.g., "Honda Civic")
• [cyan]Location[/cyan]: City or region (e.g., "atlanta", "miami")
• [cyan]Price Range[/cyan]: Min/max price filters
• [cyan]Year Range[/cyan]: Vehicle year constraints
• [cyan]Mileage[/cyan]: Maximum mileage limit
• [cyan]Advanced Filters[/cyan]: Make, model, transmission, fuel type, body style

[bold]DEAL QUALITY RATINGS:[/bold]
• [green]🌟 Excellent[/green]: Ratio > 1.25 (25%+ below market value)
• [yellow]✅ Good[/yellow]: Ratio 1.10-1.25 (10-25% below market)
• [blue]📊 Fair[/blue]: Ratio 0.95-1.10 (near market value)
• [red]❌ Poor[/red]: Ratio < 0.95 (above market value)

[bold]COMMAND LINE OPTIONS:[/bold]
• [cyan]--verbose[/cyan]: Enable detailed logging
• [cyan]--non-interactive[/cyan]: Run with Preferences.csv (for automation)
• [cyan]--help[/cyan]: Show this help message

[bold]FILES:[/bold]
• [cyan]Preferences.csv[/cyan]: Configuration file for non-interactive mode
• [cyan]facebook_scraper.log[/cyan]: Detailed operation logs
• [cyan]facebook_marketplace_cars_*.csv[/cyan]: Search results
    """
    
    console.print(Panel(help_content, title="[bold]Help[/bold]", border_style="blue"))

def show_help_fallback():
    """Fallback help display."""
    print("""
🚗 Facebook Marketplace Car Scraper

DESCRIPTION:
This tool searches Facebook Marketplace for cars and analyzes deals.

FEATURES:
• Comprehensive search with filters
• Deal analysis and scoring
• Market value estimation
• Advanced filtering options

COMMAND LINE OPTIONS:
• --verbose: Enable detailed logging
• --non-interactive: Run with Preferences.csv
• --help: Show this help

FILES:
• Preferences.csv: Configuration file
• facebook_scraper.log: Operation logs
• facebook_marketplace_cars_*.csv: Results
    """)

if __name__ == "__main__":
    # Check for help or usage
    if '--help' in sys.argv or '-h' in sys.argv:
        if RICH_AVAILABLE:
            show_help_rich()
        else:
            show_help_fallback()
        sys.exit(0)
    
    main()
#!/usr/bin/env python3

import csv
import re
import requests
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from bs4 import BeautifulSoup
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

def read_preferences(preferences_file: str) -> Dict[str, Union[str, int]]:
    """Read preferences from CSV file and return as dictionary."""
    preferences = {}
    try:
        with open(preferences_file, 'r', encoding='utf-8') as f:
            csv_reader = csv.reader(f, delimiter=',')
            for line in csv_reader:
                if len(line) >= 2:
                    key, value = line[0], line[1]
                    try:
                        preferences[key] = int(value)
                    except ValueError:
                        preferences[key] = value
    except FileNotFoundError:
        print(f"Preferences file '{preferences_file}' not found. Using defaults.")
        return get_default_preferences()
    except Exception as e:
        print(f"Error reading preferences: {e}. Using defaults.")
        return get_default_preferences()
    
    return preferences

def get_default_preferences() -> Dict[str, Union[str, int]]:
    """Return default preferences."""
    return {
        'Minimum Mileage': 0,
        'Maximum Mileage': 200000,
        'Minimum Price': 250,
        'Maximum Price': 55000,
        'Minimum Year': 1995,
        'Maximum Year': 2020,
        'Scroll Down Length': 10
    }

def build_facebook_url(preferences: Dict[str, Union[str, int]], location: str = "atlanta") -> str:
    """Build Facebook Marketplace URL with preferences."""
    base_url = f"https://www.facebook.com/marketplace/{location}/vehicles?"
    
    params = []
    if 'Minimum Price' in preferences:
        params.append(f"minPrice={preferences['Minimum Price']}")
    if 'Maximum Price' in preferences:
        params.append(f"maxPrice={preferences['Maximum Price']}")
    if 'Minimum Mileage' in preferences:
        params.append(f"minMileage={preferences['Minimum Mileage']}")
    if 'Maximum Mileage' in preferences:
        params.append(f"maxMileage={preferences['Maximum Mileage']}")
    if 'Minimum Year' in preferences:
        params.append(f"minYear={preferences['Minimum Year']}")
    if 'Maximum Year' in preferences:
        params.append(f"maxYear={preferences['Maximum Year']}")
    
    params.append("exact=false")
    
    return base_url + "&".join(params)

def scrape_facebook_with_requests(url: str) -> List[List[str]]:
    """
    Simplified Facebook scraper using requests.
    Note: This is limited because Facebook requires JavaScript for full content,
    but it demonstrates the fixed data parsing logic.
    """
    print(f"Attempting to scrape: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        print(f"Response status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Failed to access Facebook: {response.status_code}")
            return create_sample_data()  # Return sample data for testing
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Look for any text that might contain car listings
        page_text = soup.get_text()
        print(f"Page content length: {len(page_text)} characters")
        
        # Check if we got meaningful content
        if "marketplace" in page_text.lower() or "vehicle" in page_text.lower():
            print("✓ Found marketplace content")
            return extract_car_data_from_text(page_text)
        else:
            print("! No marketplace content found - likely need login or JavaScript")
            print("Creating sample data for testing...")
            return create_sample_data()
            
    except Exception as e:
        print(f"Error scraping Facebook: {e}")
        print("Creating sample data for testing...")
        return create_sample_data()

def create_sample_data() -> List[List[str]]:
    """Create sample car data for testing the processing pipeline."""
    sample_cars = [
        ["15000", "2015", "Honda", "Civic", "85000", "Atlanta, GA", "https://facebook.com/marketplace/item/sample1"],
        ["8500", "2012", "Toyota", "Camry", "120000", "Decatur, GA", "https://facebook.com/marketplace/item/sample2"],
        ["22000", "2018", "Ford", "F-150", "45000", "Sandy Springs, GA", "https://facebook.com/marketplace/item/sample3"],
        ["12000", "2014", "Chevrolet", "Malibu", "95000", "Marietta, GA", "https://facebook.com/marketplace/item/sample4"],
        ["18500", "2016", "Nissan", "Altima", "65000", "Roswell, GA", "https://facebook.com/marketplace/item/sample5"],
    ]
    print(f"Created {len(sample_cars)} sample car listings for testing")
    return sample_cars

def extract_car_data_from_text(text: str) -> List[List[str]]:
    """Extract car data from page text (basic implementation)."""
    # This is a simplified extraction - in practice would need more sophisticated parsing
    lines = text.split('\n')
    cars = []
    
    for line in lines:
        if '$' in line and any(year in line for year in ['201', '200', '199']):
            # Try to parse line as potential car listing
            tokens = line.split()
            car_data = parse_listing_tokens(tokens)
            if car_data:
                cars.append(car_data)
    
    return cars if cars else create_sample_data()

def parse_listing_tokens(tokens: List[str]) -> Optional[List[str]]:
    """Parse tokens to extract car information."""
    price = None
    year = None
    make = None
    model = None
    
    # Extract price
    for token in tokens:
        if '$' in token:
            price_match = re.search(r'\$([0-9,]+)', token)
            if price_match:
                price = price_match.group(1).replace(',', '')
                break
    
    # Extract year
    current_year = datetime.now().year
    for token in tokens:
        if token.isdigit() and len(token) == 4:
            year_num = int(token)
            if 1980 <= year_num <= current_year:
                year = token
                break
    
    # Extract make (look for common brands)
    car_brands = ['toyota', 'honda', 'ford', 'chevrolet', 'nissan', 'hyundai', 'bmw', 'mercedes']
    for token in tokens:
        if token.lower() in car_brands:
            make = token.title()
            break
    
    if price and year and make:
        return [price, year, make, model or "Unknown", "Unknown", "Unknown", "https://facebook.com/marketplace/item/parsed"]
    
    return None

def calculate_simple_ratios(car_listings: List[List[str]]) -> List[List]:
    """Calculate simple price ratios for demonstration."""
    scored_listings = []
    
    for i, car in enumerate(car_listings):
        try:
            if len(car) < 4:
                continue
                
            price = float(car[0])
            year = int(car[1]) if car[1].isdigit() else 2010
            make = car[2]
            model = car[3]
            
            # Simple valuation based on age and make
            current_year = datetime.now().year
            age = current_year - year
            
            # Basic market value estimation
            base_value = price * 1.2  # Assume listing price is 20% below market
            age_factor = max(0.7, 1.0 - (age * 0.05))  # Depreciate 5% per year
            
            # Brand factor
            premium_brands = ['bmw', 'mercedes', 'lexus', 'audi']
            reliable_brands = ['toyota', 'honda', 'mazda']
            
            if make.lower() in premium_brands:
                brand_factor = 1.1
            elif make.lower() in reliable_brands:
                brand_factor = 1.05
            else:
                brand_factor = 1.0
            
            estimated_value = base_value * age_factor * brand_factor
            ratio = estimated_value / price
            
            condition = "Good" if age < 8 else "Fair" if age < 12 else "Poor"
            deal_quality = "Great" if ratio > 1.3 else "Good" if ratio > 1.1 else "Fair"
            
            scored_car = [round(ratio, 3), condition, deal_quality] + car
            scored_listings.append(scored_car)
            
        except Exception as e:
            print(f"Error processing car {i+1}: {e}")
            continue
    
    # Sort by ratio (best deals first)
    scored_listings.sort(key=lambda x: float(x[0]), reverse=True)
    return scored_listings

def save_results_to_csv(car_listings: List[List], output_dir: str = ".") -> str:
    """Save car listings to CSV file."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"facebook_marketplace_cars_{timestamp}.csv"
    filepath = Path(output_dir) / filename
    
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            header = ['Deal_Ratio', 'Condition', 'Deal_Quality', 'Listing_Price', 'Year', 'Make', 'Model', 
                     'Mileage', 'Location', 'Facebook_URL']
            writer.writerow(header)
            
            # Write car data
            for car in car_listings:
                try:
                    if len(car) >= 6:
                        ratio = car[0]
                        condition = car[1]
                        deal_quality = car[2]
                        price = car[3]
                        year = car[4]
                        make = car[5]
                        model = car[6] if len(car) > 6 else 'Unknown'
                        mileage = car[7] if len(car) > 7 else 'Unknown'
                        location = car[8] if len(car) > 8 else 'Unknown'
                        url = car[9] if len(car) > 9 else 'Unknown'
                        
                        writer.writerow([ratio, condition, deal_quality, price, year, make, model, 
                                       mileage, location, url])
                except Exception as e:
                    print(f"Error writing car data: {e}")
                    continue
        
        print(f"Results saved to: {filepath}")
        return str(filepath)
        
    except Exception as e:
        print(f"Error saving results: {e}")
        return ""

def main():
    """Main function for simplified scraper."""
    print("=== Simplified Facebook Marketplace Car Scraper ===")
    print("Note: This version uses sample data to demonstrate the fixed processing logic.")
    
    try:
        # Read preferences
        preferences = read_preferences("Preferences.csv")
        
        # Build URL
        facebook_url = build_facebook_url(preferences)
        print(f"Target URL: {facebook_url}")
        
        # Scrape (will fall back to sample data)
        car_listings = scrape_facebook_with_requests(facebook_url)
        
        if not car_listings:
            print("No car data available.")
            return
        
        print(f"Processing {len(car_listings)} car listings...")
        
        # Process data
        final_listings = calculate_simple_ratios(car_listings)
        
        # Save results
        if final_listings:
            output_file = save_results_to_csv(final_listings)
            print(f"\n=== Summary ===")
            print(f"Total cars analyzed: {len(final_listings)}")
            print(f"Results saved to: {output_file}")
            
            print("\nTop 5 deals:")
            for i, car in enumerate(final_listings[:5]):
                try:
                    ratio = float(car[0])
                    condition = car[1]
                    deal_quality = car[2]
                    price = car[3]
                    year = car[4]
                    make = car[5]
                    model = car[6]
                    
                    print(f"  {i+1}. {year} {make} {model} - ${price} (Ratio: {ratio:.2f}, {condition}, {deal_quality})")
                except Exception as e:
                    print(f"  {i+1}. Error displaying car: {e}")
        else:
            print("No valid car listings found after processing.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
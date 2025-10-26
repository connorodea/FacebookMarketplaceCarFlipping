#!/usr/bin/env python3

import sys
import time
from facebook_car_scraper import (
    build_facebook_url, 
    read_preferences, 
    scrape_facebook_marketplace
)

def quick_test():
    """Quick test of the scraper functionality."""
    print("=== Quick Facebook Scraper Test ===")
    
    # Read preferences
    preferences = read_preferences("Preferences.csv")
    print(f"Loaded preferences: {preferences}")
    
    # Build URL
    facebook_url = build_facebook_url(preferences)
    print(f"Facebook URL: {facebook_url}")
    
    # Test scraping with minimal scrolling
    print("Testing scraping with 3 scrolls...")
    try:
        car_listings = scrape_facebook_marketplace(facebook_url, scroll_count=3)
        print(f"Found {len(car_listings)} car listings")
        
        if car_listings:
            print("\nFirst 3 listings:")
            for i, car in enumerate(car_listings[:3]):
                print(f"  {i+1}: {car}")
        else:
            print("No listings found - may need to adjust selectors")
            
    except Exception as e:
        print(f"Error during scraping: {e}")
        
    print("Test completed.")

if __name__ == "__main__":
    quick_test()
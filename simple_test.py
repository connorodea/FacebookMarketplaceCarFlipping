#!/usr/bin/env python3

from playwright.sync_api import sync_playwright
import time

def test_playwright():
    """Test basic Playwright functionality."""
    print("Testing Playwright...")
    
    try:
        with sync_playwright() as p:
            print("Launching browser...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            print("Navigating to test page...")
            page.goto("https://httpbin.org/get", timeout=30000)
            
            print("Getting page content...")
            content = page.inner_text()
            print(f"Content length: {len(content)} characters")
            
            if "httpbin" in content.lower():
                print("✓ Playwright is working correctly")
            else:
                print("✗ Unexpected content")
                
            browser.close()
            
    except Exception as e:
        print(f"✗ Playwright error: {e}")
        return False
        
    return True

def test_facebook_access():
    """Test accessing Facebook Marketplace."""
    print("\nTesting Facebook access...")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            page = context.new_page()
            
            # Test a simple Facebook page first
            print("Accessing Facebook...")
            url = "https://www.facebook.com/marketplace/atlanta/vehicles?minPrice=250&maxPrice=55000"
            
            response = page.goto(url, timeout=30000)
            print(f"Response status: {response.status}")
            
            time.sleep(3)
            
            # Check if we can see any content
            page_text = page.inner_text()
            print(f"Page text length: {len(page_text)} characters")
            
            if "marketplace" in page_text.lower() or "vehicle" in page_text.lower():
                print("✓ Successfully accessed Facebook Marketplace")
            elif "log in" in page_text.lower() or "sign up" in page_text.lower():
                print("! Facebook is asking for login - this may block scraping")
            else:
                print("? Unclear if page loaded correctly")
                print(f"Sample content: {page_text[:200]}...")
            
            browser.close()
            
    except Exception as e:
        print(f"✗ Facebook access error: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success1 = test_playwright()
    success2 = test_facebook_access()
    
    if success1 and success2:
        print("\n✓ All tests passed - the issue may be in the main script logic")
    else:
        print("\n✗ Found issues with basic functionality")
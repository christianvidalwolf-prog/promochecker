import asyncio
import random
import pandas as pd
import os
import sys
from playwright.async_api import async_playwright

# Install Playwright browsers if not already installed
def ensure_playwright_browsers():
    """Ensure Playwright browsers are installed (for cloud deployment)"""
    try:
        # Check if we're in a cloud environment
        if os.path.exists('/home/appuser'):  # Streamlit Cloud
            print("Checking for Playwright browsers...")
            import subprocess
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print("✅ Playwright Chromium installed successfully")
            else:
                print(f"⚠️ Playwright install output: {result.stdout}")
                # Try with --with-deps
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                    check=False
                )
    except Exception as e:
        print(f"Warning: Could not auto-install Playwright browsers: {e}")

# Run installation check on module import
ensure_playwright_browsers()

# Constants
INPUT_FILE = "productos.xlsx"
OUTPUT_FILE = "reporte_descuentos.xlsx"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

async def check_promotion(page, url):
    """
    Navigates to the URL and checks for promotions or discounts.
    Returns a tuple (status, details, current_price, normal_price, discount_label).
    """
    try:
        print(f"Checking URL: {url}")
        
        # Retry logic for navigation
        max_retries = 2
        for attempt in range(max_retries):
            try:
                # Add protocol if missing
                target_url = url if url.startswith("http") else f"https://{url}"
                await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                break # Success
            except Exception as e:
                print(f"Attempt {attempt+1} failed for {url}: {e}")
                if attempt == max_retries - 1:
                    return "Error/Timeout", "Timeout loading page (60s)", "N/A", "N/A", "N/A"
                await asyncio.sleep(2) # Short wait before retry
        
        # Simulate human behavior
        await page.wait_for_timeout(random.randint(2000, 4000))
        
        # Check for CAPTCHA title
        title = await page.title()
        if "CAPTCHA" in title or "Robot Check" in title:
            return "Error/Captcha", "Amazon detected unusual traffic", "N/A", "N/A", "N/A"

        promo_detected = False
        details = []
        current_price = "Not Found" # Translated
        
        # --- 0. EXTRACT CURRENT PRICE (Selling Price) ---
        # Priority: Look for ".priceToPay" first, as this is the actual active price
        price_selectors = [
            ".priceToPay .a-offscreen",                 # Most accurate for deals
            ".priceToPay span[aria-hidden='true']",     # Backup
            "#corePrice_feature_div .a-price.priceToPay .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price.priceToPay .a-offscreen",
            
            # Fallbacks (General)
            "#corePrice_feature_div .a-price .a-offscreen", 
            ".a-price.a-text-price.a-size-medium .a-offscreen",
            ".a-price .a-offscreen"
        ]
        
        found_prices = []
        for selector in price_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    text = await el.text_content()
                    if text:
                        clean_val = text.strip()
                        # Avoid saving empty strings or non-price text
                        if any(c.isdigit() for c in clean_val):
                            found_prices.append(clean_val)
            
            # If we found matches with high-priority selectors (priceToPay), stop there
            if found_prices and "priceToPay" in selector:
                break
        
        # Logic: properly determine which is current vs normal if multiple found
        # Usually checking the first valid one found by priority selectors is enough
        if found_prices:
            current_price = found_prices[0] # Take the best match
        else:
            current_price = "Not Found" 
        
        # --- 1. Check for deal badges ---
        deal_selectors = [
            # Generic Badges
            ".badge-text", 
            "#dealBadge",
            ".a-badge-label", 
            ".promo-badge",
            
            # Coupons & vouchers
            "#coupon-badge",
            ".vpc-coupon-label",
            "label:has-text('Apply coupon')",
            "label:has-text('Aplicar cupón')", # Keep Spanish too
            "label:has-text('Apply voucher')",
            
            # Limited time deals
            "#lightning-deal-timer",
            ".dealPriceText",
            
            # Amazon's Choice & Best Seller
            "#acBadge_feature_div",      # Amazon's Choice container
            ".ac-badge-wrapper",          # Amazon's Choice wrapper
            ".ac-keyword-link",           # "Amazon's Choice de..."
            "#bestSellerBadge_feature_div", # Best Seller container
            ".zg-badge-body",             # Best Seller body
        ]
        
        for selector in deal_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    text = await el.text_content()
                    # Clean up text
                    clean_text = text.strip().replace("\n", " ") if text else ""
                    
                    # Specific check for Amazon's Choice which might have empty text in container
                    if "acBadge" in selector or "ac-badge" in selector:
                         promo_detected = True
                         details.append("Amazon's Choice detected")
                    elif "bestSeller" in selector:
                         promo_detected = True
                         details.append("Best Seller detected")
                    elif clean_text:
                        promo_detected = True
                        details.append(f"Badge: {clean_text[:50]}...")

        # --- Helper: Price Cleaner ---
        def parse_price(price_str):
            if not price_str: return 0.0
            try:
                # Remove symbols, spaces, keep only digits and separators
                # Supports 1.234,56 format (European) and 1,234.56 (US)
                clean = price_str.replace("€", "").replace("$", "").replace("£", "").strip()
                if "," in clean and "." in clean: # 1.234,56 or 1,234.56
                    if clean.find(",") > clean.find("."): # 1.234,56 (EU)
                        clean = clean.replace(".", "").replace(",", ".")
                    else: # 1,234.56 (US)
                        clean = clean.replace(",", "")
                elif "," in clean: # 12,34 (EU)
                    clean = clean.replace(",", ".")
                return float(clean)
            except:
                return 0.0

        # --- SMART PRICE ANALYSIS ---
        # Instead of trusting specific selectors, we gather ALL prices in the main block
        # and use logic: Lowest = Price to Pay, Highest = List/Old Price.
        
        found_prices = []
        raw_price_map = {} # Map float val -> string representation
        
        # Broad scan for any price container in the buy box area
        price_containers = [
             "#corePrice_feature_div .a-price .a-offscreen",
             "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
             "#apex_desktop .a-price .a-offscreen",
             ".a-price .a-offscreen", # Generic fallback
             ".a-text-price span[aria-hidden='true']" # Strike-through text often here
        ]
        
        for selector in price_containers:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    text = await el.text_content()
                    if text:
                        cleaned_text = text.strip()
                        val = parse_price(cleaned_text)
                        if val > 0:
                            found_prices.append(val)
                            if val not in raw_price_map:
                                raw_price_map[val] = cleaned_text

        # Determine Prices based on Values
        current_price_val = 0.0
        normal_price_val = 0.0
        
        current_price = "Not Found"
        normal_price = "N/A"
        discount_label = "N/A"

        if found_prices:
            # Sort unique prices
            unique_prices = sorted(list(set(found_prices)))
            
            # The lowest price is ALWAYS the current selling price
            current_price_val = unique_prices[0]
            current_price = raw_price_map[current_price_val]
            
            # If we have multiple prices, the highest is likely the list price
            if len(unique_prices) > 1:
                potential_normal = unique_prices[-1]
                # Only accept if it's at least 2% higher to avoid currency glitch
                if potential_normal > current_price_val * 1.02:
                    normal_price_val = potential_normal
                    normal_price = raw_price_map[normal_price_val]
                    promo_detected = True
                    details.append(f"Price Drop: {normal_price} -> {current_price}")
                    
                    # Calculate discount manually if not found later
                    calc_discount = int(((normal_price_val - current_price_val) / normal_price_val) * 100)
                    if discount_label == "N/A":
                        discount_label = f"-{calc_discount}%"

        # --- Discount Badges (Text Confirmation) ---
        # Look for explicit percentage badges to double check
        try:
            potential_discounts = await page.query_selector_all("span.savingsPercentage, span.a-size-large.a-color-price, div:has-text('%')")
            for el in potential_discounts:
                 if await el.is_visible():
                    text = await el.text_content()
                    if text and "%" in text and ("-" in text or "off" in text.lower()):
                        clean_disc = text.strip()
                        # Update discount label if we found a visual badge (often more reliable than calc)
                        if len(clean_disc) < 15: # Safety check
                            discount_label = clean_disc
                            promo_detected = True
                            if "Discount Found" not in str(details):
                                details.append(f"Discount Badge: {discount_label}")
                            break
        except:
            pass

        unique_details = "; ".join(sorted(list(set(details))))
        
        if promo_detected:
            return "ACTIVE", unique_details, current_price, normal_price, discount_label
        else:
            return "NO PROMO", "No badges or visible discounts detected", current_price, normal_price, discount_label

    except Exception as e:
        print(f"Error checking {url}: {e}")
        return "Error/Exception", str(e), "Error", "Error", "Error"

async def process_products(df, progress_callback=None, headless=True):
    """
    Process a DataFrame of products and check for promotions.
    Compatible with Streamlit app.
    """
    if "URL" not in df.columns:
        raise ValueError("The dataframe must have a 'URL' column")

    estados = []
    detalles_list = []
    precios_actuales = []
    precios_normales = []
    descuentos_labels = []
    
    total = len(df)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        for index, row in df.iterrows():
            url = row['URL']
            
            # Update progress
            if progress_callback:
                progress_callback((index) / total)
            
            status, details, price, norm_price, disc_label = await check_promotion(page, url)
            
            estados.append(status)
            detalles_list.append(details)
            precios_actuales.append(price)
            precios_normales.append(norm_price)
            descuentos_labels.append(disc_label)
            
            # Random delay
            if index < total - 1:
                delay = random.uniform(2, 5)
                await asyncio.sleep(delay)
                
        await browser.close()
        
    df["Promo Status"] = estados
    df["Details"] = detalles_list
    df["Current Price"] = precios_actuales
    df["Normal Price"] = precios_normales
    df["Discount"] = descuentos_labels
    
    # Final progress update
    if progress_callback:
        progress_callback(1.0)
        
    return df

async def main():
    try:
        print("Reading input file...")
        df = pd.read_excel(INPUT_FILE)
        
        print("Starting check...")
        # Wrapper to print progress to console
        def console_progress(p):
            print(f"Progress: {p*100:.0f}%")

        df = await process_products(df, progress_callback=console_progress, headless=False)

        print(f"Saving report to {OUTPUT_FILE}...")
        df.to_excel(OUTPUT_FILE, index=False)
        print("Process completed!")

    except FileNotFoundError:
        print(f"Error: File {INPUT_FILE} not found")
    except Exception as e:
        print(f"Fatal error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

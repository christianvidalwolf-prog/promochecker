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
    Returns a tuple (status, details, current_price).
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
                    return "Error/Timeout", "Tiempo de espera agotado al cargar (60s)", "N/A"
                await asyncio.sleep(2) # Short wait before retry
        
        # Simulate human behavior
        await page.wait_for_timeout(random.randint(2000, 4000))
        
        # Check for CAPTCHA title
        title = await page.title()
        if "CAPTCHA" in title or "Robot Check" in title:
            return "Error/Captcha", "Amazon detectó tráfico inusual", "N/A"

        promo_detected = False
        details = []
        current_price = "No encontrado"

        # --- 0. EXTRACT CURRENT PRICE ---
        price_selectors = [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            "#apex_desktop .a-price .a-offscreen",
            ".a-price.a-text-price.a-size-medium .a-offscreen",
            ".a-price .a-offscreen"
        ]
        
        for selector in price_selectors:
            price_el = await page.query_selector(selector)
            if price_el and await price_el.is_visible():
                price_text = await price_el.text_content()
                if price_text:
                    current_price = price_text.strip()
                    break 

        # --- 1. Check for deal badges (Etiquetas y Ofertas) ---
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
            "label:has-text('Aplicar cupón')",
            
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
                         details.append("Amazon's Choice detectado")
                    elif "bestSeller" in selector:
                         promo_detected = True
                         details.append("Más vendido detectado")
                    elif clean_text:
                        promo_detected = True
                        details.append(f"Etiqueta: {clean_text[:50]}...")

        # --- 2. Check for Discount (Price strike-through or percentage off) ---
        normal_price = "N/A"
        discount_label = "N/A"
        
        # Method A: Savings Percentage (Explicit XX% off)
        savings_selectors = [
            ".savingsPercentage",
            ".a-size-large.a-color-price.savingPriceOverride", # Sometimes used
            "span[class*='savingsPercentage']"
        ]
        
        for sel in savings_selectors:
            savings_el = await page.query_selector(sel)
            if savings_el and await savings_el.is_visible():
                savings_text = await savings_el.text_content()
                if savings_text:
                    promo_detected = True
                    discount_label = savings_text.strip()
                    details.append(f"Descuento explícito: {discount_label}")
        
        # Method B: Strike-through price structure (Precio anterior vs Actual)
        # Search in core price block
        core_price_div = await page.query_selector("#corePrice_feature_div")
        if core_price_div:
            # Look for strict strike-through data attribute
            basis_el = await core_price_div.query_selector(".a-text-price[data-a-strike='true'] span[aria-hidden='true']")
            
            # Fallback: Check for any text-price that looks like a strike-through
            if not basis_el:
                 basis_el = await core_price_div.query_selector(".a-text-price span.a-offscreen")
            
            if basis_el:
                 basis_text = await basis_el.text_content()
                 if basis_text and basis_text.strip() != current_price: # Ensure it's different from current price
                    promo_detected = True
                    normal_price = basis_text.strip()
                    details.append(f"Precio tachado (Anterior): {normal_price}")

        unique_details = "; ".join(sorted(list(set(details))))
        
        if promo_detected:
            return "ACTIVO", unique_details, current_price, normal_price, discount_label
        else:
            return "SIN PROMOCIÓN", "No se detectaron etiquetas ni descuentos visibles", current_price, normal_price, discount_label

    except Exception as e:
        print(f"Error checking {url}: {e}")
        return "Error/Exception", str(e), "Error", "Error", "Error"

async def process_products(df, progress_callback=None, headless=True):
    """
    Process a DataFrame of products and check for promotions.
    Compatible with Streamlit app.
    """
    if "URL" not in df.columns:
        raise ValueError("El dataframe debe tener una columna 'URL'")

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
        
    df["Estado Promoción"] = estados
    df["Detalles"] = detalles_list
    df["Precio Actual"] = precios_actuales
    df["Precio Normal"] = precios_normales
    df["Descuento"] = descuentos_labels
    
    # Final progress update
    if progress_callback:
        progress_callback(1.0)
        
    return df

async def main():
    try:
        print("Leyendo archivo de entrada...")
        df = pd.read_excel(INPUT_FILE)
        
        print("Iniciando revisión...")
        # Wrapper to print progress to console
        def console_progress(p):
            print(f"Progreso: {p*100:.0f}%")

        df = await process_products(df, progress_callback=console_progress, headless=False)

        print(f"Guardando reporte en {OUTPUT_FILE}...")
        df.to_excel(OUTPUT_FILE, index=False)
        print("¡Proceso completado!")

    except FileNotFoundError:
        print(f"Error: No se encontró el archivo {INPUT_FILE}")
    except Exception as e:
        print(f"Error fatal: {e}")

if __name__ == "__main__":
    asyncio.run(main())

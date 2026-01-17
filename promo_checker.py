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

        # --- 1. Check for deal badges ---
        deal_selectors = [
            ".badge-text", 
            "#dealBadge",
            ".a-badge-label", 
            "#coupon-badge",
            ".promo-badge",
            "#lightning-deal-timer",
            ".vpc-coupon-label"
        ]
        
        for selector in deal_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                if await el.is_visible():
                    text = await el.text_content()
                    if text and text.strip():
                        promo_detected = True
                        details.append(f"Etiqueta detectada: {text.strip()}")

        # Check for Coupon Checkbox explicitly
        coupon_checkbox = await page.query_selector("label:has-text('Apply coupon')")
        if coupon_checkbox:
             promo_detected = True
             details.append("Cupón aplicable encontrado")
        
        # --- 2. Check for Discount (Price strike-through or percentage off) ---
        savings_selector = ".savingsPercentage"
        savings_el = await page.query_selector(savings_selector)
        if savings_el and await savings_el.is_visible():
            savings_text = await savings_el.text_content()
            if savings_text:
                promo_detected = True
                details.append(f"Descuento encontrado: {savings_text.strip()}")
        
        # Strike-through price basis - STRICT CHECK
        core_price_div = await page.query_selector("#corePrice_feature_div")
        if core_price_div:
            basis_el = await core_price_div.query_selector(".a-text-price[data-a-strike='true'] span[aria-hidden='true']")
            if basis_el:
                 basis_text = await basis_el.text_content()
                 if basis_text:
                    promo_detected = True
                    details.append(f"Precio tachado visible: {basis_text.strip()}")

        unique_details = "; ".join(sorted(list(set(details))))
        
        if promo_detected:
            return "ACTIVO", unique_details, current_price
        else:
            return "SIN PROMOCIÓN", "No se detectaron etiquetas ni descuentos visibles", current_price

    except Exception as e:
        print(f"Error checking {url}: {e}")
        return "Error/Exception", str(e), "Error"

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
            
            status, details, price = await check_promotion(page, url)
            estados.append(status)
            detalles_list.append(details)
            precios_actuales.append(price)
            
            # Random delay
            if index < total - 1:
                delay = random.uniform(2, 5)
                await asyncio.sleep(delay)
                
        await browser.close()
        
    df["Estado Promoción"] = estados
    df["Detalles"] = detalles_list
    df["Precio Actual"] = precios_actuales
    
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

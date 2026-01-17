
def parse_price(price_str):
    if not price_str:
        return None
    try:
        # Clean string: remove currency symbol, whitespace, set decimal point
        clean = price_str.replace("€", "").replace("$", "").strip()
        clean = clean.replace(".", "").replace(",", ".") # European format: 1.234,56 -> 1234.56
        return float(clean)
    except:
        return None

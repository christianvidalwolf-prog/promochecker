import pandas as pd

try:
    df = pd.DataFrame({'URL': [
        'https://www.amazon.es/dp/B08N5W4N65', 
        'https://www.amazon.es/dp/B09G9F5T3N',
        'https://www.amazon.es/dp/B07PGV7C9Q'
    ]})
    df.to_excel('productos.xlsx', index=False)
    print("Archivo 'productos.xlsx' creado exitosamente.")
except ImportError:
    print("Error: Necesitas instalar pandas y openpyxl primero.")
    print("Ejecuta: pip install pandas openpyxl")
except Exception as e:
    print(f"Ocurrió un error: {e}")

import streamlit as st
import pandas as pd
import asyncio
from promo_checker import process_products
from io import BytesIO

st.set_page_config(page_title="Amazon Promo Checker", page_icon="🛒", layout="wide")

# Custom CSS for Futuristic UI
st.markdown("""
<style>
    /* Import Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Inter:wght@300;400;600&display=swap');

    /* Global Theme & Text */
    .stApp {
        background-color: #050510;
        background-image: radial-gradient(circle at 50% 50%, #1a1a40 0%, #000000 100%);
        font-family: 'Inter', sans-serif;
        color: #e0e0e0;
    }
    
    p, li, label, .stMarkdown {
        color: #e0e0e0 !important;
        font-size: 1.05rem;
    }

    /* Headings */
    h1, h2, h3 {
        font-family: 'Orbitron', sans-serif !important;
        background: linear-gradient(90deg, #00f2ff, #bc13fe);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0px 0px 10px rgba(0, 242, 255, 0.3);
    }

    /* Buttons - Interactive & Futuristic */
    div.stButton > button {
        background: rgba(0, 242, 255, 0.1);
        border: 1px solid #00f2ff;
        color: #00f2ff;
        font-family: 'Orbitron', sans-serif;
        font-size: 16px;
        border-radius: 8px;
        padding: 0.6em 1.2em;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
        box-shadow: 0 0 10px rgba(0, 242, 255, 0.1);
        letter-spacing: 1px;
        width: 100%; 
    }

    div.stButton > button:hover {
        transform: translateY(-3px) scale(1.02);
        background: linear-gradient(90deg, #00f2ff, #008cff);
        color: #000 !important;
        border: 1px solid #00f2ff;
        box-shadow: 0 0 25px rgba(0, 242, 255, 0.6), 0 0 5px rgba(255, 255, 255, 0.8) inset;
    }

    div.stButton > button:active {
        transform: translateY(-1px);
        box-shadow: 0 0 10px rgba(0, 242, 255, 0.4);
    }
    
    /* File Uploader - Minimal Button Style */
    [data-testid='stFileUploader'] {
        padding: 0;
    }
    [data-testid='stFileUploader'] section {
        background-color: transparent;
        border: 1px dashed #00f2ff;
        padding: 10px;
        min-height: 0px;
    }
    [data-testid='stFileUploader'] button {
        background: linear-gradient(90deg, #bc13fe, #00f2ff);
        color: white;
        border: none;
        border-radius: 5px;
    }
    
    /* Progress Bar */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #00f2ff, #bc13fe);
        box-shadow: 0 0 10px rgba(188, 19, 254, 0.5);
    }
    
    /* Dataframes */
    [data-testid="stDataFrame"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(0, 242, 255, 0.2);
        box-shadow: 0 0 15px rgba(0, 0, 0, 0.5);
        border-radius: 5px;
    }
    
    [data-testid="stDataFrame"] th {
        background-color: #02020a !important;
        color: #00f2ff !important;
        font-family: 'Orbitron', sans-serif;
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #02020a;
        border-right: 1px solid rgba(0, 242, 255, 0.1);
    }

</style>
""", unsafe_allow_html=True)

st.title("🛒 AMAZON PROMO CHECKER")
st.markdown("""
Esta aplicación verifica automáticamente si los productos de Amazon tienen promociones o descuentos activos.
1. **Sube** tu archivo Excel (.xlsx) o CSV (.csv).
2. **Configura** las opciones.
3. **Descarga** el reporte con los resultados.
""")

# Sidebar settings
st.sidebar.header("Configuración")

# Auto-detect if we're running in a cloud environment (Streamlit Cloud has no display)
import os
is_cloud = os.path.exists('/home/appuser')  # Streamlit Cloud path

if is_cloud:
    st.sidebar.info("🌐 Ejecutando en la nube - Modo headless está activado automáticamente")
    headless = True
else:
    headless = st.sidebar.checkbox("Modo Oculto (Headless)", value=False, help="Si se desactiva, verás el navegador abriéndose y navegando.")


uploaded_file = st.file_uploader("Cargar archivo Excel (.xlsx) o CSV (.csv)", type=["xlsx", "csv"])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'):
            try:
                df = pd.read_csv(uploaded_file, encoding='utf-8-sig') # Handle optional BOM
            except UnicodeDecodeError:
                df = pd.read_csv(uploaded_file, encoding='latin1') # Fallback
        else:
            df = pd.read_excel(uploaded_file)
        
        # Validation and Transformation
        if "URL" not in df.columns and "ASIN" in df.columns:
            st.info("ℹ️ Se detectó columna 'ASIN'. Generando URLs para Amazon.de...")
            df["URL"] = df["ASIN"].apply(lambda x: f"https://www.amazon.de/dp/{str(x).strip()}")

        if "URL" not in df.columns:
            st.error("❌ El archivo NO tiene una columna llamada 'URL' ni 'ASIN'. Por favor corrige el archivo.")
            st.write("Columnas encontradas:", list(df.columns))
        else:
            st.subheader("Vista Previa")
            st.dataframe(df.head())
            st.info(f"Se encontraron {len(df)} productos para revisar.")
            
            # Initialize session state for results if not present
            if 'results' not in st.session_state:
                st.session_state.results = None

            # Start Button
            if st.button("🚀 Iniciar Revisión"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                status_text.text("Iniciando motores...")
                
                def update_progress(p):
                    progress_bar.progress(p)
                    status_text.text(f"Procesando: {int(p*100)}%")

                try:
                    with st.spinner("Escaneando productos en Amazon..."):
                        try:
                            loop = asyncio.get_event_loop()
                        except RuntimeError:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                        
                        result_df = loop.run_until_complete(process_products(df.copy(), progress_callback=update_progress, headless=headless))
                        st.session_state.results = result_df
                        
                    st.success("✅ ¡Proceso completado!")
                    st.balloons()

                except Exception as e:
                    st.error(f"Ocurrió un error: {e}")
                    import traceback
                    traceback.print_exc()

            # Retry Logic
            if st.session_state.results is not None:
                df_res = st.session_state.results
                
                if "Estado Promoción" in df_res.columns:
                    error_mask = df_res["Estado Promoción"].astype(str).str.contains("Error/Timeout")
                    errors_count = error_mask.sum()
                    
                    if errors_count > 0:
                        st.warning(f"⚠️ Se detectaron {errors_count} errores de tiempo de espera.")
                        if st.button("🔄 Reintentar SOLO errores"):
                            st.info("Reintentando URLs fallidas...")
                            failed_df = df_res[error_mask].copy()
                            retry_progress = st.progress(0)
                            
                            def update_retry(p):
                                retry_progress.progress(p)
                            
                            try:
                                try:
                                    loop = asyncio.get_event_loop()
                                except RuntimeError:
                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    
                                fixed_df = loop.run_until_complete(process_products(failed_df, progress_callback=update_retry, headless=headless))
                                st.session_state.results.update(fixed_df)
                                st.success("✅ Reintento completado. Tabla actualizada.")
                                st.rerun() 
                                
                            except Exception as e:
                                st.error(f"Error al reintentar: {e}")

            # Display Results if they exist
            if st.session_state.results is not None:
                result_df = st.session_state.results
                
                st.subheader("Resultados")
                    
                def highlight_status(val):
                    color = 'green' if val == 'ACTIVO' else 'red' if 'Error' in str(val) else 'black'
                    return f'color: {color}; font-weight: bold'

                st.dataframe(
                    result_df.style.map(highlight_status, subset=['Estado Promoción']),
                    column_config={
                        "URL": st.column_config.LinkColumn("Product Link")
                    }
                )
                    
                # Download button with Hyperlinks (Excel)
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    result_df.to_excel(writer, index=False, sheet_name='Reporte')
                    
                    workbook = writer.book
                    worksheet = writer.sheets['Reporte']
                    
                    url_col_idx = None
                    for idx, col_name in enumerate(result_df.columns):
                        if col_name == "URL":
                            url_col_idx = idx + 1
                            break
                    
                    if url_col_idx:
                        for row_idx, url in enumerate(result_df["URL"]):
                            cell = worksheet.cell(row=row_idx + 2, column=url_col_idx)
                            if url and isinstance(url, str) and url.startswith("http"):
                                cell.hyperlink = url
                                cell.style = "Hyperlink"
                                
                output.seek(0)
                
                st.download_button(
                    label="📥 Descargar Reporte Final",
                    data=output,
                    file_name="reporte_promociones.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key='download-btn'
                )

    except Exception as e:
        st.error(f"Error al leer el archivo: {e}")

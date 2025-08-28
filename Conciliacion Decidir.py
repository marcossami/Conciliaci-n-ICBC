import streamlit as st
import pandas as pd
import numpy as np
import io

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Conciliación Multicanal", layout="wide")
st.title("Conciliación Multicanal")

# Inicializo la clave si no existe
if "canal" not in st.session_state:
    st.session_state["canal"] = None

# =========================
# Selector de marketplace (único visible al inicio)
# =========================
st.session_state["canal"] = st.radio(
    "¿Qué marketplace querés conciliar?",
    ["ICBC Mall", "Carrefour"],
    index=None,            # <- SIN selección automática
    horizontal=True,
    key="canal"
)

# Si no hay selección, CORTA aquí y no muestres nada más
if st.session_state["canal"] is None:
    st.stop()

# Botón para cambiar canal (resetea y corta)
def reset_canal():
    st.session_state["canal"] = None
st.button("Cambiar canal", on_click=reset_canal)

# =========================
# Helpers comunes
# =========================
def normalize_money(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
              .str.replace(r'[^\d,.\-]', '', regex=True)
              .str.replace(',', '.', regex=False)
              .replace({'': np.nan})
              .pipe(pd.to_numeric, errors='coerce')
    )

def normalize_id(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
              .str.split('-', n=1).str[0]
              .str.extract(r'(\d+)', expand=False)
    )

# =========================
# ICBC Mall — tu flujo original
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # 1) Decidir
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = df_dec.columns.str.strip().str.lower()
        df_dec['estado'] = df_dec['estado'].astype(str).str.lower()
        df_dec = df_dec[df_dec['estado'] == 'acreditada']

        first_col = df_dec.columns[0]
        df_dec['idoper'] = (
            df_dec[first_col].astype(str)
                 .str.split('-', n=1).str[0]
                 .str.extract(r'(\d+)', expand=False)
        )

        fecha_cols_dec = [c for c in df_dec.columns if 'fecha' in c]
        df_dec['monto_decidir'] = (
            df_dec['monto'].astype(str)
                 .str.replace(r'[^\d,.-]', '', regex=True)
                 .str.replace(',', '.', regex=False)
                 .pipe(pd.to_numeric, errors='coerce')
        )

        agg_dec = {col: 'min' for col in fecha_cols_dec}
        agg_dec['monto_decidir'] = 'sum'
        dec_group = df_dec.groupby('idoper', dropna=True).agg(agg_dec).reset_index()

        # 2) Aper
        df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC", engine='openpyxl')
        df_ape.columns = df_ape.columns.str.strip().str.lower()
        carrito_col = next(c for c in df_ape.columns if 'carrito' in c)
        df_ape['carrito'] = (
            df_ape[carrito_col].astype(str)
                  .










































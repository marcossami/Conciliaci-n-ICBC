import streamlit as st
import pandas as pd
import numpy as np
import io

# =========================
# CONFIG INICIAL
# =========================
st.set_page_config(page_title="Conciliación General", layout="wide")
st.title("Conciliación General")

# =========================
# DESPLEGABLE INICIAL (único visible al inicio)
# =========================
OPTIONS = ["(seleccionar)", "ICBC Mall", "Carrefour"]
canal = st.selectbox("¿Qué marketplace querés conciliar?", OPTIONS, index=0)
if canal == "(seleccionar)":
    st.stop()

# =========================
# HELPERS
# =========================
def normalize_money(series: pd.Series, dash_as_zero: bool = False) -> pd.Series:
    s = series.astype(str)
    if dash_as_zero:
        s = s.str.replace(r'^\s*-\s*$', '0', regex=True)
    return (
        s.str.replace(r'[^\d,.\-]', '', regex=True)
         .str.replace(',', '.', regex=False)
         .replace({'': np.nan})
         .pipe(pd.to_numeric, errors='coerce')
    )

def ctc_id_norm(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    out = s.str.extract(r'^[A-Za-z]+-(\d+)-', expand=False)
    return out.fillna(s.str.extract(r'(\d{6,})', expand=False))

def carrefour_id_norm(series: pd.Series) -> pd.Series:
    s = series.astype(str)
    out = s.str.extract(r'^[A-Za-z]+-(\d+)-', expand=False)
    return out.fillna(s.str.extract(r'(\d{6,})', expand=False))

def dedupe_columns(cols) -> list:
    seen = {}
    out = []
    for c in cols:
        base = str(c).strip() if c is not None else "unnamed"
        if base == "" or base.lower().startswith("unnamed"):
            base = "unnamed"
        if base in seen:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")
        else:
            seen[base] = 0
            out.append(base)
    return out

def find_no_ctc_amount_column(columns) -> str | None:
    target = "pvp total c/iva"
    for c in columns:
        normalized = " ".join(str(c).split()).strip().lower()
        if normalized == target:
            return c
    return None

# =========================
# ICBC MALL
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = dedupe_columns(df_dec.columns)
        df_dec['estado'] = df_dec['estado'].astype(str).str.lower()
        df_dec = df_dec[df_dec['estado'] == 'acreditada']

        first_col = df_dec.columns[0]
        df_dec['idoper'] = (
            df_dec[first_col].astype(str)
                 .str.split('-', n=1).str[0]
                 .str.extract(r'(\d+)', expand=False)
        )

        fecha_cols_dec = [c for c in df_dec.columns if 'fecha' in c]
        df_dec['monto_decidir'] = normalize_money(df_dec['monto'])

        agg_dec = {col: 'min' for col in fecha_cols_dec}
        agg_dec['monto_decidir'] = 'sum'
        dec_group = df_dec.groupby('idoper', dropna=True).agg(agg_dec).reset_index()

        df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC", engine='openpyxl')
        df_ape.columns = dedupe_columns(df_ape.columns)
        carrito_col = next(c for c in df_ape.columns if 'carrito' in c.lower())
        df_ape['carrito'] = (
            df_ape[carrito_col].astype(str)
                  .str.split('-', n=1).str[0]
                  .str.extract(r'(\d+)', expand=False)
        )

        fecha_cols_ape = [c for c in df_ape.columns if 'fecha' in c]
        cost_col = next(c for c in df_ape.columns if 'costo' in c and 'producto' in c)
        df_ape['costoproducto'] = normalize_money(df_ape[cost_col])

        agg_ape = {col: 'min' for col in fecha_cols_ape}
        agg_ape['costoproducto'] = 'sum'
        ape_group = df_ape.groupby('carrito', dropna=True).agg(agg_ape).reset_index()

        total_dec = dec_group['monto_decidir'].sum()
        total_ape = ape_group['costoproducto'].sum()
        diff_total = total_dec - total_ape
        diff_abs = abs(diff_total)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Decidir", f"{total_dec:,.2f}")
        c2.metric("Total Aper", f"{total_ape:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        df_matched = pd.merge(dec_group, ape_group, left_on='idoper', right_on='carrito', how='inner')
        df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

        def style_mismatch(row):
            return ['background-color: red; font-weight: bold;' if row['diferencia'] != 0 else '' for _ in row]

        st.subheader("Conciliación por ID")
        st.dataframe(df_matched.style.apply(style_mismatch, axis=1), height=500)

# =========================
# CARREFOUR
# =========================
def run_carrefour():
    st.header("Carrefour Marketplace — CTC vs NO CTC")

    c1, c2 = st.columns(2)
    with c1:
        file_no_ctc = st.file_uploader("Subí **Reporte Carrefour (NO CTC)** (.xlsx)", type=["xlsx"], key="carrefour_rep")
    with c2:
        file_ctc    = st.file_uploader("Subí **Reporte CTC** (.xlsx)", type=["xlsx"], key="ctc_rep")

    if file_ctc and file_no_ctc:
        # ---------- CTC ----------
        df_ctc = pd.read_excel(file_ctc, engine="openpyxl")
        df_ctc.columns = dedupe_columns(df_ctc.columns)
        col_id_ctc = df_ctc.columns[0]   # Col A
        col_m_ctc  = df_ctc.columns[19]  # Col T
        df_ctc["_id_norm"] = ctc_id_norm(df_ctc[col_id_ctc])
        df_ctc["_monto"]   = normalize_money(df_ctc[col_m_ctc])
        ctc_group = df_ctc.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto":"monto_ctc"})
        st.dataframe(df_ctc.head(10))   # <-- preview seguro (dedupe hecho)

        # ---------- NO CTC ----------
        df_no = pd.read_excel(file_no_ctc, engine="openpyxl")
        df_no.columns = dedupe_columns(df_no.columns)
        col_id_no = df_no.columns[1]  # Col B
        df_no["_id_norm"] = carrefour_id_norm(df_no[col_id_no])
        col_m_no = find_no_ctc_amount_column(df_no.columns)
        df_no["_monto"] = normalize_money(df_no[col_m_no], dash_as_zero=True)
        no_group = df_no.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto":"monto_no_ctc"})
        st.dataframe(df_no.head(10))   # <-- preview seguro (dedupe hecho)

        # ---------- Conciliación ----------
        m = pd.merge(no_group, ctc_group, on="_id_norm", how="outer").fillna(0)
        m["diferencia"] = m["monto_no_ctc"] - m["monto_ctc"]

        def style_mismatch(row):
            return ['background-color: red; font-weight: bold;' if row['diferencia'] != 0 else '' for _ in row]

        st.subheader("Conciliación por ID (NO CTC - CTC)")
        st.dataframe(m.style.apply(style_mismatch, axis=1), height=480)

# =========================
# ROUTER
# =========================
if canal == "ICBC Mall":
    run_icbc()
elif canal == "Carrefour":
    run_carrefour()
































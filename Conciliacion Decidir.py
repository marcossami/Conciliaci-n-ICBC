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
    """
    Convierte montos a float, tolerando símbolos, puntos/comas.
    Si dash_as_zero=True, convierte el guion solitario '-' a 0.
    """
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
    """
    CTC: 'CRR-1538786970403-01' -> '1538786970403'
    """
    s = series.astype(str)
    out = s.str.extract(r'^[A-Za-z]+-(\d+)-', expand=False)
    return out.fillna(s.str.extract(r'(\d{6,})', expand=False))

def carrefour_id_norm(series: pd.Series) -> pd.Series:
    """
    NO CTC: 'CRF-1547297149746-01' -> '1547297149746'
    """
    s = series.astype(str)
    out = s.str.extract(r'^[A-Za-z]+-(\d+)-', expand=False)
    return out.fillna(s.str.extract(r'(\d{6,})', expand=False))

def dedupe_columns(cols) -> list:
    """
    Hace únicos los nombres de columnas preservando orden.
    'Col', 'Col' -> 'Col', 'Col_1'
    Además recorta espacios y trata 'Unnamed:*' como 'unnamed'.
    """
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
    """
    Busca la columna 'PVP TOTAL C/IVA' en NO CTC ignorando saltos de línea y espacios.
    Devuelve el nombre real de la columna si la encuentra, si no None.
    """
    target = "pvp total c/iva"
    for c in columns:
        normalized = " ".join(str(c).split()).strip().lower()  # compacta \n y espacios
        if normalized == target:
            return c
    return None

# =========================
# ICBC MALL — (tu lógica original intacta)
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # 1) Decidir (filtra Acreditada)
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = df_dec.columns.str.strip().str.lower()
        df_dec['estado'] = df_dec['estado'].astype(str).str.lower()
        df_dec = df_dec[df_dec['estado'] == 'acreditada']

        # ID (solo dígitos antes del guion, según tu código original)
        first_col = df_dec.columns[0]
        df_dec['idoper'] = (
            df_dec[first_col].astype(str)
                 .str.split('-', n=1).str[0]
                 .str.extract(r'(\d+)', expand=False)
        )

        # Fechas + monto
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
                  .str.split('-', n=1).str[0]
                  .str.extract(r'(\d+)', expand=False)
        )

        fecha_cols_ape = [c for c in df_ape.columns if 'fecha' in c]
        cost_col = next(c for c in df_ape.columns if 'costo' in c and 'producto' in c)
        df_ape['costoproducto'] = (
            df_ape[cost_col].astype(str)
                  .str.replace(r'[^\d,.-]', '', regex=True)
                  .str.replace(',', '.', regex=False)
                  .pipe(pd.to_numeric, errors='coerce')
        )

        agg_ape = {col: 'min' for col in fecha_cols_ape}
        agg_ape['costoproducto'] = 'sum'
        ape_group = df_ape.groupby('carrito', dropna=True).agg(agg_ape).reset_index()

        # Totales
        total_dec = dec_group['monto_decidir'].sum()
        total_ape = ape_group['costoproducto'].sum()
        diff_total = total_dec - total_ape
        diff_abs = abs(diff_total)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Decidir", f"{total_dec:,.2f}")
        c2.metric("Total Aper", f"{total_ape:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        # Mutualidad
        set_dec = set(dec_group['idoper'])
        set_ape = set(ape_group['carrito'])
        falt_aper    = sorted(set_dec - set_ape)
        falt_decider = sorted(set_ape - set_dec)
        if not falt_aper and not falt_decider:
            st.success("Todos los registros acreditados fueron encontrados correctamente.")
        else:
            if falt_aper:
                st.error("IDoper que faltan en Aper: " + ", ".join(map(str, falt_aper)))
            if falt_decider:
                st.error("Carritos en Aper que no están en Decidir: " + ", ".join(map(str, falt_decider)))

        # Match por ID
        df_matched = pd.merge(dec_group, ape_group, left_on='idoper', right_on='carrito', how='inner', suffixes=('_dec','_ape'))
        df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

        final_cols = (['idoper', 'carrito'] + fecha_cols_dec + ['monto_decidir'] + fecha_cols_ape + ['costoproducto', 'diferencia'])
        df_result = df_matched[final_cols]

        def style_mismatch(row):
            return ['background-color: red; font-weight: bold;' if row['diferencia'] != 0 else '' for _ in row]

        st.subheader("Registros Conciliados")
        st.dataframe(df_result.style.apply(style_mismatch, axis=1), height=500)

        st.subheader("Decidir acreditadas sin Aper")
        st.dataframe(dec_group[~dec_group['idoper'].isin(ape_group['carrito'])], height=200)

        st.subheader("Aper sin Decidir acreditadas")
        st.dataframe(ape_group[~ape_group['carrito'].isin(dec_group['idoper'])], height=200)

        # Export
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_result.to_excel(writer, sheet_name='Conciliados', index=False)
            dec_group[~dec_group['idoper'].isin(ape_group['carrito'])].to_excel(writer, sheet_name='Decidir_sin_Aper', index=False)
            ape_group[~ape_group['carrito'].isin(dec_group['idoper'])].to_excel(writer, sheet_name='Aper_sin_Decidir', index=False)
        output.seek(0)
        st.download_button("Descargar conciliación ICBC", output, "conciliacion_ICBC.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Subí ambos archivos para iniciar la conciliación.")

# =========================
# CARREFOUR — CTC vs NO CTC
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
        df_ctc.columns = dedupe_columns(df_ctc.columns)   # evita error por columnas duplicadas
        if df_ctc.shape[1] < 20:
            st.error("El archivo CTC debe tener al menos 20 columnas (para usar la columna T como monto).")
            st.stop()

        col_id_ctc = df_ctc.columns[0]    # Col A: ID Venta
        col_m_ctc  = df_ctc.columns[19]   # Col T: monto

        df_ctc["_id_norm"] = ctc_id_norm(df_ctc[col_id_ctc])
        df_ctc["_monto"]   = normalize_money(df_ctc[col_m_ctc])

        ctc_group = (df_ctc.groupby("_id_norm", dropna=True)["_monto"]
                          .sum()
                          .reset_index()
                          .rename(columns={"_monto": "monto_ctc"}))

        # ---------- NO CTC ----------
        df_no = pd.read_excel(file_no_ctc, engine="openpyxl")
        df_no.columns = dedupe_columns(df_no.columns)      # evita error por columnas duplicadas

        if df_no.shape[1] < 2:
            st.error("El archivo NO CTC debe tener al menos 2 columnas (para usar la columna B: Numero de Orden).")
            st.stop()

        # Col B: Numero de Orden (fijo)
        col_id_no = df_no.columns[1]
        df_no["_id_norm"] = carrefour_id_norm(df_no[col_id_no])

        # Monto: buscar columna 'PVP TOTAL C/IVA' (con o sin saltos de línea)
        col_m_no = find_no_ctc_amount_column(df_no.columns)
        if col_m_no is None:
            st.error("No se encontró la columna de monto 'PVP TOTAL C/IVA' en el NO CTC.")
            st.stop()

        # '-' (guion) = monto nulo -> 0
        df_no["_monto"] = normalize_money(df_no[col_m_no], dash_as_zero=True)

        no_group = (df_no.groupby("_id_norm", dropna=True)["_monto"]
                         .sum()
                         .reset_index()
                         .rename(columns={"_monto": "monto_no_ctc"}))

        # ---------- IDs presentes/ausentes ----------
        ids_ctc = set(ctc_group["_id_norm"].dropna())
        ids_no  = set(no_group["_id_norm"].dropna())
        solo_ctc = sorted(ids_ctc - ids_no)
        solo_no  = sorted(ids_no - ids_ctc)

        st.subheader("IDs en CTC y no en NO CTC")
        st.write(", ".join(map(str, solo_ctc)) if solo_ctc else "— Ninguno —")

        st.subheader("IDs en NO CTC y no en CTC")
        st.write(", ".join(map(str, solo_no)) if solo_no else "— Ninguno —")

        # ---------- Totales ----------
        total_ctc = ctc_group["monto_ctc"].sum(skipna=True)
        total_no  = no_group["monto_no_ctc"].sum(skipna=True)
        diff_total = total_no - total_ctc
        diff_abs   = abs(diff_total)

        if diff_total == 0:
            resumen = "✅ Ambos tienen el mismo monto."
        elif diff_total > 0:
            resumen = f"❌ NO CTC es mayor por {diff_abs:,.2f}."
        else:
            resumen = f"❌ CTC es mayor por {diff_abs:,.2f}."

        c1, c2, c3 = st.columns(3)
        c1.metric("Total CTC (col T)", f"{total_ctc:,.2f}")
        c2.metric("Total NO CTC (PVP TOTAL C/IVA)", f"{total_no:,.2f}")
        c3.metric("Diferencia abs.", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")
        st.info(resumen)

        # ---------- Conciliación por ID ----------
        m = pd.merge(no_group, ctc_group, on="_id_norm", how="outer")
        m["monto_no_ctc"] = m["monto_no_ctc"].fillna(0)
        m["monto_ctc"]    = m["monto_ctc"].fillna(0)
        m["diferencia"]   = m["monto_no_ctc"] - m["monto_ctc"]

        def style_mismatch(row):
            return ['background-color: red; font-weight: bold;' if row['diferencia'] != 0 else '' for _ in row]

        st.subheader("Conciliación por ID (NO CTC - CTC)")
        st.dataframe(
            m[["_id_norm", "monto_no_ctc", "monto_ctc", "diferencia"]]
             .sort_values("diferencia")
             .style.apply(style_mismatch, axis=1),
            height=480
        )

        # ---------- Descarga ----------
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
            m.to_excel(writer, sheet_name="Conciliados", index=False)
            pd.DataFrame({"id_solo_ctc": solo_ctc}).to_excel(writer, sheet_name="CTC_sin_NOCTC", index=False)
            pd.DataFrame({"id_solo_no_ctc": solo_no}).to_excel(writer, sheet_name="NOCTC_sin_CTC", index=False)
        out.seek(0)
        st.download_button("Descargar conciliación Carrefour", out, "conciliacion_Carrefour.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.info("Subí ambos archivos para iniciar la conciliación.")

# =========================
# ROUTER
# =========================
if canal == "ICBC Mall":
    run_icbc()
elif canal == "Carrefour":
    run_carrefour()




























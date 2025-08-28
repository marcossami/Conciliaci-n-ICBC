import streamlit as st
import pandas as pd
import numpy as np
import io

# =========================
# CONFIG INICIAL
# =========================
st.set_page_config(page_title="Conciliador Multicanal", layout="wide")
st.title("Conciliación Multicanal")

# =========================
# PASO 1: Selector de canal
# =========================
CANAL = st.radio(
    "Elegí el canal a conciliar",
    ["(seleccionar)", "ICBC Mall", "Carrefour"],
    index=0,
    horizontal=True
)

# =========================
# HELPERS COMUNES
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
# ICBC MALL — tu lógica intacta
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Sube el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Sube el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # ... aquí va tu código ICBC tal cual (sin cambios) ...
        st.success("Proceso ICBC ejecutado correctamente (placeholder).")
    else:
        st.info("Subí ambos archivos para iniciar la conciliación.")

# =========================
# CARREFOUR — Marketplace
# =========================
def run_carrefour():
    st.header("Carrefour Marketplace — Reporte Carrefour vs Reporte CTC")

    c1, c2 = st.columns(2)
    with c1:
        file_carrefour = st.file_uploader("Subí **Reporte Carrefour** (.xlsx)", type=["xlsx"], key="carrefour_rep")
    with c2:
        file_ctc       = st.file_uploader("Subí **Reporte CTC** (.xlsx)", type=["xlsx"], key="ctc_rep")

    if file_carrefour and file_ctc:
        # Lectura
        df_car = pd.read_excel(file_carrefour, engine="openpyxl")
        df_ctc = pd.read_excel(file_ctc, engine="openpyxl")
        df_car.columns = df_car.columns.str.strip()
        df_ctc.columns = df_ctc.columns.str.strip()

        st.write("Vista previa (primeras filas):")
        p1, p2 = st.columns(2)
        with p1:
            st.caption("Reporte Carrefour")
            st.dataframe(df_car.head(10))
        with p2:
            st.caption("Reporte CTC")
            st.dataframe(df_ctc.head(10))

        # ---------------- Configuración de Matching ----------------
        st.markdown("### Configuración de Matching")
        cols_car = list(df_car.columns)
        cols_ctc = list(df_ctc.columns)

        # IDs para join
        id_car = st.selectbox("Columna ID en **Carrefour** para matchear", cols_car, key="id_car")
        id_ctc = st.selectbox("Columna ID en **CTC** para matchear", cols_ctc, key="id_ctc")

        # Monto en Carrefour (configurable)
        monto_car = st.selectbox("Columna **Monto** en Carrefour", cols_car, key="monto_car")

        # Monto en CTC (FIJO: Columna T = índice 19)
        if df_ctc.shape[1] >= 20:
            m_ctc_col = df_ctc.columns[19]  # Columna T
            st.success(f"Usando SIEMPRE la columna T de CTC: **{m_ctc_col}**")
        else:
            st.error("El archivo CTC no tiene columna T (mínimo 20 columnas). Verificá el formato.")
            st.stop()

        # (Opcional) Fecha
        fecha_car = st.selectbox("Columna **Fecha** en Carrefour (opcional)", ["(ninguna)"] + cols_car, index=0, key="fecha_car")
        fecha_ctc = st.selectbox("Columna **Fecha** en CTC (opcional)", ["(ninguna)"] + cols_ctc, index=0, key="fecha_ctc")

        # ---------------- Normalización ----------------
        df_car["_id_norm"] = normalize_id(df_car[id_car])
        df_ctc["_id_norm"] = normalize_id(df_ctc[id_ctc])

        df_car["_monto"] = normalize_money(df_car[monto_car])
        df_ctc["_monto"] = normalize_money(df_ctc[m_ctc_col])

        if fecha_car != "(ninguna)":
            df_car["_fecha"] = pd.to_datetime(df_car[fecha_car], errors="coerce")
        else:
            df_car["_fecha"] = pd.NaT

        if fecha_ctc != "(ninguna)":
            df_ctc["_fecha"] = pd.to_datetime(df_ctc[fecha_ctc], errors="coerce")
        else:
            df_ctc["_fecha"] = pd.NaT

        # Agrupar por ID
        car_group = df_car.groupby("_id_norm", dropna=True).agg({
            "_monto": "sum",
            "_fecha": "min"
        }).rename(columns={"_monto": "monto_carrefour", "_fecha": "fecha_carrefour"}).reset_index()

        ctc_group = df_ctc.groupby("_id_norm", dropna=True).agg({
            "_monto": "sum",
            "_fecha": "min"
        }).rename(columns={"_monto": "monto_ctc", "_fecha": "fecha_ctc"}).reset_index()

        # Totales
        total_car = car_group["monto_carrefour"].sum(skipna=True)
        total_ctc = ctc_group["monto_ctc"].sum(skipna=True)
        diff_total = total_car - total_ctc
        diff_abs = abs(diff_total)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Carrefour", f"{total_car:,.2f}")
        c2.metric("Total CTC (columna T)", f"{total_ctc:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        # Merge
        m = pd.merge(car_group, ctc_group, on="_id_norm", how="outer")
        m["diferencia"] = (m["monto_carrefour"].fillna(0) - m["monto_ctc"].fillna(0))

        # Resultados
        st.subheader("Conciliados por ID")
        cols_show = ["_id_norm", "monto_carrefour", "monto_ctc", "diferencia", "fecha_carrefour", "fecha_ctc"]
        cols_show = [c for c in cols_show if c in m.columns]
        st.dataframe(m[cols_show].sort_values("diferencia"), height=480)

        # Solo en uno u otro
        car_solo = car_group[~car_group["_id_norm"].isin(ctc_group["_id_norm"])].copy()
        ctc_solo = ctc_group[~ctc_group["_id_norm"].isin(car_group["_id_norm"])].copy()

        st.subheader("Carrefour sin CTC")
        st.dataframe(car_solo, height=200)

        st.subheader("CTC sin Carrefour")
        st.dataframe(ctc_solo, height=200)

        # Descarga
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            m.to_excel(writer, sheet_name="Conciliados", index=False)
            car_solo.to_excel(writer, sheet_name="Carrefour_sin_CTC", index=False)
            ctc_solo.to_excel(writer, sheet_name="CTC_sin_Carrefour", index=False)

            wb = writer.book
            fmt_money = wb.add_format({'num_format': '#,##0.00'})
            for sheet, df in [("Conciliados", m), ("Carrefour_sin_CTC", car_solo), ("CTC_sin_Carrefour", ctc_solo)]:
                ws = writer.sheets[sheet]
                for colname in ["monto_carrefour", "monto_ctc", "diferencia"]:
                    if colname in df.columns:
                        idx = df.columns.get_loc(colname)
                        ws.set_column(idx, idx, None, fmt_money)

        output.seek(0)
        st.download_button(
            label="Descargar conciliación Carrefour",
            data=output,
            file_name="conciliacion_Carrefour.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Subí ambos archivos para iniciar la conciliación.")

# =========================
# ROUTER
# =========================
if CANAL == "(seleccionar)":
    st.info("Seleccioná un canal para comenzar.")
elif CANAL == "ICBC Mall":
    run_icbc()
elif CANAL == "Carrefour":
    run_carrefour()



































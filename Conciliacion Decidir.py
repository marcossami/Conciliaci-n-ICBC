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
# PASO 1: Selector de marketplace (ÚNICO visible al inicio)
# =========================
CANAL = st.radio(
    "¿Qué marketplace querés conciliar?",
    ["(seleccionar)", "ICBC Mall", "Carrefour"],
    index=0,
    horizontal=True
)

# Si todavía no se eligió canal, no mostrar NADA más
if CANAL == "(seleccionar)":
    st.stop()

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
    # Toma parte antes del guion y extrae dígitos
    return (
        series.astype(str)
              .str.split('-', n=1).str[0]
              .str.extract(r'(\d+)', expand=False)
    )

# =========================
# ICBC MALL — (tu lógica original intacta)
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # 1) Leer y filtrar sólo “Acreditada” desde Decidir
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = df_dec.columns.str.strip().str.lower()
        df_dec['estado'] = df_dec['estado'].astype(str).str.lower()
        df_dec = df_dec[df_dec['estado'] == 'acreditada']

        # Extraer idoper (solo dígitos antes del guion)
        first_col = df_dec.columns[0]
        df_dec['idoper'] = (
            df_dec[first_col].astype(str)
                 .str.split('-', n=1).str[0]
                 .str.extract(r'(\d+)', expand=False)
        )

        # Columnas de fecha y conversión de monto
        fecha_cols_dec = [c for c in df_dec.columns if 'fecha' in c]
        df_dec['monto_decidir'] = (
            df_dec['monto'].astype(str)
                 .str.replace(r'[^\d,.-]', '', regex=True)
                 .str.replace(',', '.', regex=False)
                 .pipe(pd.to_numeric, errors='coerce')
        )

        # Agrupar Decidir
        agg_dec = {col: 'min' for col in fecha_cols_dec}
        agg_dec['monto_decidir'] = 'sum'
        dec_group = (
            df_dec
            .groupby('idoper', dropna=True)
            .agg(agg_dec)
            .reset_index()
        )

        # 2) Leer y preparar Aper
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

        # Agrupar Aper
        agg_ape = {col: 'min' for col in fecha_cols_ape}
        agg_ape['costoproducto'] = 'sum'
        ape_group = (
            df_ape
            .groupby('carrito', dropna=True)
            .agg(agg_ape)
            .reset_index()
        )

        # 3) Mostrar totales y diferencia global
        total_dec = dec_group['monto_decidir'].sum()
        total_ape = ape_group['costoproducto'].sum()
        diff_total = total_dec - total_ape
        diff_abs = abs(diff_total)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total Decidir", f"{total_dec:,.2f}")
        c2.metric("Total Aper", f"{total_ape:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        # 4) Validar mutualidad de IDs
        set_dec = set(dec_group['idoper'])
        set_ape = set(ape_group['carrito'])
        falt_aper    = sorted(set_dec - set_ape)
        falt_decider = sorted(set_ape - set_dec)
        if not falt_aper and not falt_decider:
            st.success("Todos los registros acreditados fueron encontrados correctamente.")
        else:
            if falt_aper:
                st.error("IDoper acreditadas que faltan en Aper: " + ", ".join(map(str, falt_aper)))
            if falt_decider:
                st.error("Carritos en Aper que no están en acreditadas de Decidir: " + ", ".join(map(str, falt_decider)))

        # 5) Conciliación y diferencia por registro
        df_matched = pd.merge(
            dec_group, ape_group,
            left_on='idoper', right_on='carrito',
            how='inner',
            suffixes=('_dec','_ape')
        )
        df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

        final_cols = (
            ['idoper', 'carrito']
            + fecha_cols_dec + ['monto_decidir']
            + fecha_cols_ape + ['costoproducto', 'diferencia']
        )
        df_result = df_matched[final_cols]

        # 5a) Resaltar filas donde "diferencia" ≠ 0
        def style_mismatch(row):
            if row['diferencia'] != 0:
                return ['background-color: red; font-weight: bold;' for _ in row]
            else:
                return ['' for _ in row]

        styled = df_result.style.apply(style_mismatch, axis=1)

        st.subheader("Registros Conciliados")
        st.dataframe(styled, height=500)

        # 6) Mostrar no-matches
        st.subheader("Decidir acreditadas sin Aper")
        df_dec_sin = dec_group[~dec_group['idoper'].isin(ape_group['carrito'])]
        st.dataframe(df_dec_sin, height=200)

        st.subheader("Aper sin Decidir acreditadas")
        df_ape_sin = ape_group[~ape_group['carrito'].isin(dec_group['idoper'])]
        st.dataframe(df_ape_sin, height=200)

        # 7) Descargar Excel final
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_result.to_excel(writer, sheet_name='Conciliados', index=False)
            df_dec_sin.to_excel(writer, sheet_name='Decidir_sin_Aper', index=False)
            df_ape_sin.to_excel(writer, sheet_name='Aper_sin_Decidir', index=False)
            wb = writer.book
            yellow = wb.add_format({'bg_color': '#FFFF00'})
            for sheet_name, df_un in [
                ('Decidir_sin_Aper', df_dec_sin),
                ('Aper_sin_Decidir', df_ape_sin)
            ]:
                ws = writer.sheets[sheet_name]
                rows, cols = df_un.shape
                ws.conditional_format(1, 0, rows, cols - 1, {'type': 'no_blanks', 'format': yellow})
        output.seek(0)
        st.download_button(
            label="Descargar conciliación completa",
            data=output,
            file_name="conciliacion_ICBC.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Subí ambos archivos para iniciar la conciliación.")

# =========================
# CARREFOUR — Marketplace (CTC usa SIEMPRE columna T)
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

        # Vista previa (opcional para validar)
        p1, p2 = st.columns(2)
        with p1:
            st.caption("Reporte Carrefour (primeras filas)")
            st.dataframe(df_car.head(10))
        with p2:
            st.caption("Reporte CTC (primeras filas)")
            st.dataframe(df_ctc.head(10))

        # ---------------- Configuración de Matching ----------------
        st.markdown("### Configuración de Matching")
        cols_car = list(df_car.columns)
        cols_ctc = list(df_ctc.columns)

        # IDs para join (dejamos seleccionable hasta confirmar definitivos)
        id_car = st.selectbox("Columna ID en **Carrefour** para matchear", cols_car, key="id_car")
        id_ctc = st.selectbox("Columna ID en **CTC** para matchear", cols_ctc, key="id_ctc")

        # Monto en Carrefour (configurable)
        monto_car = st.selectbox("Columna **Monto** en Carrefour", cols_car, key="monto_car")

        # Monto en CTC: SIEMPRE columna T (índice 19)
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
# ROUTER: muestra sólo el bloque elegido
# =========================
if CANAL == "ICBC Mall":
    run_icbc()
elif CANAL == "Carrefour":
    run_carrefour()






































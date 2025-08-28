import streamlit as st
import pandas as pd
import numpy as np
import io
import re

# =========================
# CONFIG INICIAL
# =========================
st.set_page_config(page_title="Conciliación Multicanal", layout="wide")

# ==================================
# LÓGICA DE LA PÁGINA DE SELECCIÓN
# ==================================

# Este es el ÚNICO widget que se muestra inicialmente
canal_elegido = st.radio(
    "Elegí el canal a conciliar",
    ["(seleccionar)", "ICBC Mall", "Carrefour"],
    index=0,
    horizontal=True
)

# A partir de aquí, la lógica SOLO se ejecuta si se ha seleccionado un canal
if canal_elegido == "ICBC Mall":
    st.title("Conciliación Multicanal")
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # 1) Read and prepare DataFrames
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = df_dec.columns.str.strip().str.lower()
        
        # Filter only 'acreditada' status
        df_dec = df_dec[df_dec['estado'].astype(str).str.lower() == 'acreditada']
        
        # Normalize ID and Amount
        id_col_dec = "idoper" # Asumiendo un nombre de columna fijo por simplicidad
        monto_col_dec = "monto" # Asumiendo un nombre de columna fijo
        if id_col_dec not in df_dec.columns:
            st.warning("Columna 'idoper' no encontrada. Se buscará por palabra clave.")
            id_col_dec = [col for col in df_dec.columns if 'idoper' in col.lower() or 'id' in col.lower()][0]
        if monto_col_dec not in df_dec.columns:
            st.warning("Columna 'monto' no encontrada. Se buscará por palabra clave.")
            monto_col_dec = [col for col in df_dec.columns if 'monto' in col.lower() or 'importe' in col.lower()][0]

        df_dec['idoper'] = df_dec[id_col_dec].astype(str).str.split('-', n=1).str[0].str.extract(r'(\d+)', expand=False)
        df_dec['monto_decidir'] = df_dec[monto_col_dec].astype(str).str.replace(r'[^\d,.\-]', '', regex=True).str.replace(',', '.', regex=False).pipe(pd.to_numeric, errors='coerce')

        # Group Decidir
        dec_group = df_dec.groupby('idoper', dropna=True)['monto_decidir'].sum().reset_index()

        df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC", engine='openpyxl')
        df_ape.columns = df_ape.columns.str.strip().str.lower()
        
        # Normalize ID and Amount
        id_col_ape = "carrito" # Asumiendo un nombre de columna fijo
        monto_col_ape = "costoproducto" # Asumiendo un nombre de columna fijo
        if id_col_ape not in df_ape.columns:
            st.warning("Columna 'carrito' no encontrada. Se buscará por palabra clave.")
            id_col_ape = [col for col in df_ape.columns if 'carrito' in col.lower() or 'id' in col.lower()][0]
        if monto_col_ape not in df_ape.columns:
            st.warning("Columna 'costoproducto' no encontrada. Se buscará por palabra clave.")
            monto_col_ape = [col for col in df_ape.columns if 'costo' in col.lower() or 'monto' in col.lower()][0]

        df_ape['carrito'] = df_ape[id_col_ape].astype(str).str.split('-', n=1).str[0].str.extract(r'(\d+)', expand=False)
        df_ape['costoproducto'] = df_ape[monto_col_ape].astype(str).str.replace(r'[^\d,.\-]', '', regex=True).str.replace(',', '.', regex=False).pipe(pd.to_numeric, errors='coerce')

        # Group Aper
        ape_group = df_ape.groupby('carrito', dropna=True)['costoproducto'].sum().reset_index()

        # 2) Display totals and global difference
        total1 = dec_group['monto_decidir'].sum(skipna=True)
        total2 = ape_group['costoproducto'].sum(skipna=True)
        diff_total = total1 - total2
        diff_abs = abs(diff_total)
        
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Total Decidir", f"{total1:,.2f}")
        c2.metric(f"Total Aper", f"{total2:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        # 3) Reconciliation
        df_matched = pd.merge(dec_group, ape_group, left_on='idoper', right_on='carrito', how='inner', suffixes=('_dec','_ape'))
        df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

        st.subheader("Registros Conciliados")
        def style_mismatches(df: pd.DataFrame, column: str):
            def style_row(row):
                if row[column] != 0:
                    return ['background-color: #ffcccc; font-weight: bold;'] * len(row)
                else:
                    return [''] * len(row)
            return df.style.apply(style_row, axis=1)
        st.dataframe(style_mismatches(df_matched, 'diferencia'), height=500, use_container_width=True)

        # 4) Display non-matches
        st.subheader("Registros sin Match")
        df_dec_sin_ape = dec_group[~dec_group['idoper'].isin(ape_group['carrito'])]
        st.info(f"Decidir acreditadas sin Aper: {len(df_dec_sin_ape)} registros")
        st.dataframe(df_dec_sin_ape, use_container_width=True)

        df_ape_sin_dec = ape_group[~ape_group['carrito'].isin(dec_group['idoper'])]
        st.info(f"Aper sin Decidir acreditadas: {len(df_ape_sin_dec)} registros")
        st.dataframe(df_ape_sin_dec, use_container_width=True)

        # 5) Download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_matched.to_excel(writer, sheet_name='Conciliados', index=False)
            df_dec_sin_ape.to_excel(writer, sheet_name='Decidir_sin_Aper', index=False)
            df_ape_sin_dec.to_excel(writer, sheet_name='Aper_sin_Decidir', index=False)
        output.seek(0)
        
        st.download_button(
            label="Descargar conciliación completa",
            data=output,
            file_name="conciliacion_ICBC.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Por favor, subí ambos archivos para iniciar la conciliación.")

elif canal_elegido == "Carrefour":
    st.title("Conciliación Multicanal")
    st.header("Carrefour Marketplace — Reporte Carrefour vs Reporte CTC")

    c1, c2 = st.columns(2)
    with c1:
        file_carrefour = st.file_uploader("Subí **Reporte Carrefour** (.xlsx)", type=["xlsx"], key="carrefour_rep")
    with c2:
        file_ctc = st.file_uploader("Subí **Reporte CTC** (.xlsx)", type=["xlsx"], key="ctc_rep")

    if file_carrefour and file_ctc:
        df_car = pd.read_excel(file_carrefour, engine="openpyxl")
        df_ctc = pd.read_excel(file_ctc, engine="openpyxl")
        df_car.columns = df_car.columns.str.strip().str.lower()
        df_ctc.columns = df_ctc.columns.str.strip().str.lower()

        # Selection of columns
        id_car = st.selectbox("Columna ID en **Carrefour** para matchear", list(df_car.columns))
        id_ctc = st.selectbox("Columna ID en **CTC** para matchear", list(df_ctc.columns))
        monto_car = st.selectbox("Columna **Monto** en Carrefour", list(df_car.columns))
        
        # Assuming 'T' (index 19) is the column for CTC
        if df_ctc.shape[1] > 19:
            m_ctc_col = df_ctc.columns[19]
            st.success(f"Usando la columna T del CTC: **{m_ctc_col}**")
        else:
            st.warning("El archivo CTC no tiene la columna T (índice 19). Por favor, revisá el archivo.")
            st.stop()


        # Normalization and grouping
        df_car["_id_norm"] = df_car[id_car].astype(str).str.split('-', n=1).str[0].str.extract(r'(\d+)', expand=False)
        df_ctc["_id_norm"] = df_ctc[id_ctc].astype(str).str.split('-', n=1).str[0].str.extract(r'(\d+)', expand=False)
        df_car["_monto"] = df_car[monto_car].astype(str).str.replace(r'[^\d,.\-]', '', regex=True).str.replace(',', '.', regex=False).pipe(pd.to_numeric, errors='coerce')
        df_ctc["_monto"] = df_ctc[m_ctc_col].astype(str).str.replace(r'[^\d,.\-]', '', regex=True).str.replace(',', '.', regex=False).pipe(pd.to_numeric, errors='coerce')

        car_group = df_car.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto": "monto_carrefour"})
        ctc_group = df_ctc.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto": "monto_ctc"})

        # Totals
        total1 = car_group['monto_carrefour'].sum(skipna=True)
        total2 = ctc_group['monto_ctc'].sum(skipna=True)
        diff_total = total1 - total2
        diff_abs = abs(diff_total)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Carrefour", f"{total1:,.2f}")
        c2.metric("Total CTC", f"{total2:,.2f}")
        c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

        # Merge and difference per record
        m = pd.merge(car_group, ctc_group, on="_id_norm", how="outer")
        m["diferencia"] = m["monto_carrefour"].fillna(0) - m["monto_ctc"].fillna(0)

        st.subheader("Conciliados por ID")
        def style_mismatches(df: pd.DataFrame, column: str):
            def style_row(row):
                if row[column] != 0:
                    return ['background-color: #ffcccc; font-weight: bold;'] * len(row)
                else:
                    return [''] * len(row)
            return df.style.apply(style_row, axis=1)
        st.dataframe(style_mismatches(m, 'diferencia'), height=400, use_container_width=True)
        
        # Download
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            m.to_excel(writer, sheet_name='Conciliados', index=False)
        output.seek(0)
        
        st.download_button(
            label="Descargar conciliación Carrefour",
            data=output,
            file_name="conciliacion_Carrefour.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Por favor, subí ambos archivos para iniciar la conciliación.")























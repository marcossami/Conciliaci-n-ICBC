import streamlit as st
import pandas as pd
import numpy as np
import io
import re

# =========================
# CONFIG INICIAL Y TITULO
# =========================
st.set_page_config(page_title="Conciliación Multicanal", layout="wide")
st.title("Conciliación Multicanal")

# =========================
# FUNCIONES AUXILIARES (HELPERS)
# =========================

def normalize_money(series: pd.Series) -> pd.Series:
    """Normaliza una columna de Pandas a formato numérico (float)."""
    return (
        series.astype(str)
              .str.replace(r'[^\d,.\-]', '', regex=True)
              .str.replace(',', '.', regex=False)
              .pipe(pd.to_numeric, errors='coerce')
    )

def normalize_id(series: pd.Series) -> pd.Series:
    """Extrae y normaliza un ID (parte numérica antes de un guion)."""
    return (
        series.astype(str)
              .str.split('-', n=1).str[0]
              .str.extract(r'(\d+)', expand=False)
    )

def get_col_by_keyword(df: pd.DataFrame, keywords: list[str]) -> str:
    """Busca una columna en el DataFrame que contenga una de las palabras clave."""
    for col in df.columns:
        for keyword in keywords:
            if keyword in col.lower():
                return col
    return None

def calculate_and_display_totals(df1: pd.DataFrame, df2: pd.DataFrame, col1: str, col2: str, title1: str, title2: str):
    """Calcula y muestra los totales y la diferencia entre dos dataframes."""
    total1 = df1[col1].sum(skipna=True)
    total2 = df2[col2].sum(skipna=True)
    diff_total = total1 - total2
    diff_abs = abs(diff_total)
    
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Total {title1}", f"{total1:,.2f}")
    c2.metric(f"Total {title2}", f"{total2:,.2f}")
    c3.metric("Diferencia", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")

def style_mismatches(df: pd.DataFrame, column: str):
    """Aplica formato condicional para resaltar filas con diferencias."""
    def style_row(row):
        if row[column] != 0:
            return ['background-color: #ffcccc; font-weight: bold;'] * len(row)
        else:
            return [''] * len(row)
    return df.style.apply(style_row, axis=1)

def get_excel_writer(dataframes: dict, output_file: io.BytesIO):
    """Genera un archivo Excel con múltiples hojas y formato condicional."""
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        for sheet_name, df_data in dataframes.items():
            df_data.to_excel(writer, sheet_name=sheet_name, index=False)
            
            # Formato condicional para las hojas que lo necesiten
            if sheet_name in ["Decidir_sin_Aper", "Aper_sin_Decidir"]:
                workbook = writer.book
                worksheet = writer.sheets[sheet_name]
                yellow_format = workbook.add_format({'bg_color': '#FFFF00'})
                rows, cols = df_data.shape
                if rows > 0:
                    worksheet.conditional_format(1, 0, rows, cols - 1, {'type': 'no_blanks', 'format': yellow_format})
    return output_file

# =========================
# PASO 1: Desplegable (único visible al inicio)
# =========================
canal = st.selectbox(
    "Elegí el canal a conciliar",
    ["(seleccionar)", "ICBC Mall", "Carrefour"],
    index=0
)

# Si no hay selección, NO mostrar nada más.
if canal == "(seleccionar)":
    st.info("Elegí un canal para iniciar la conciliación.")
    st.stop()

# =========================
# LÓGICA DE ICBC MALL
# =========================
if canal == "ICBC Mall":
    st.header("ICBC Mall — Decidir vs Aper")

    uploaded_decidir = st.file_uploader("Subí el reporte de Decidir (.xlsx)", type="xlsx", key="decidir_icbc")
    uploaded_aper    = st.file_uploader("Subí el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="aper_icbc")

    if uploaded_decidir and uploaded_aper:
        # 1) Leer y preparar DataFrames
        df_dec = pd.read_excel(uploaded_decidir, engine='openpyxl')
        df_dec.columns = df_dec.columns.str.strip().str.lower()
        
        # Filtrar solo estado 'acreditada'
        df_dec = df_dec[df_dec['estado'].astype(str).str.lower() == 'acreditada']
        
        # Normalizar ID y Monto
        id_col_dec = get_col_by_keyword(df_dec, ["idoper", "id"])
        monto_col_dec = get_col_by_keyword(df_dec, ["monto"])
        df_dec['idoper'] = normalize_id(df_dec[id_col_dec])
        df_dec['monto_decidir'] = normalize_money(df_dec[monto_col_dec])

        # Agrupar Decidir
        dec_group = df_dec.groupby('idoper', dropna=True)['monto_decidir'].sum().reset_index()

        df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC", engine='openpyxl')
        df_ape.columns = df_ape.columns.str.strip().str.lower()
        
        # Normalizar ID y Monto
        id_col_ape = get_col_by_keyword(df_ape, ["carrito", "id_operacion", "id"])
        monto_col_ape = get_col_by_keyword(df_ape, ["costoproducto", "monto"])
        df_ape['carrito'] = normalize_id(df_ape[id_col_ape])
        df_ape['costoproducto'] = normalize_money(df_ape[monto_col_ape])

        # Agrupar Aper
        ape_group = df_ape.groupby('carrito', dropna=True)['costoproducto'].sum().reset_index()

        # 2) Mostrar totales y diferencia global
        calculate_and_display_totals(dec_group, ape_group, 'monto_decidir', 'costoproducto', 'Decidir', 'Aper')

        # 3) Conciliación
        df_matched = pd.merge(dec_group, ape_group, left_on='idoper', right_on='carrito', how='inner', suffixes=('_dec','_ape'))
        df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

        st.subheader("Registros Conciliados")
        st.dataframe(style_mismatches(df_matched, 'diferencia'), height=500, use_container_width=True)

        # 4) Mostrar no-matches
        st.subheader("Registros sin Match")
        df_dec_sin_ape = dec_group[~dec_group['idoper'].isin(ape_group['carrito'])]
        st.info(f"Decidir acreditadas sin Aper: {len(df_dec_sin_ape)} registros")
        st.dataframe(df_dec_sin_ape, use_container_width=True)

        df_ape_sin_dec = ape_group[~ape_group['carrito'].isin(dec_group['idoper'])]
        st.info(f"Aper sin Decidir acreditadas: {len(df_ape_sin_dec)} registros")
        st.dataframe(df_ape_sin_dec, use_container_width=True)

        # 5) Descargar
        output = io.BytesIO()
        data_to_excel = {
            'Conciliados': df_matched,
            'Decidir_sin_Aper': df_dec_sin_ape,
            'Aper_sin_Decidir': df_ape_sin_dec
        }
        output = get_excel_writer(data_to_excel, output)
        output.seek(0)
        
        st.download_button(
            label="Descargar conciliación completa",
            data=output,
            file_name="conciliacion_ICBC.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Por favor, subí ambos archivos para iniciar la conciliación.")

# =========================
# LÓGICA DE CARREFOUR
# =========================
if canal == "Carrefour":
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

        # Selección de columnas (se usan selectbox si no se puede fijar)
        id_car = st.selectbox("Columna ID en **Carrefour** para matchear", list(df_car.columns))
        id_ctc = st.selectbox("Columna ID en **CTC** para matchear", list(df_ctc.columns))
        monto_car = st.selectbox("Columna **Monto** en Carrefour", list(df_car.columns))
        
        # Asumiendo que 'T' (índice 19) es la columna para CTC
        m_ctc_col = df_ctc.columns[19]
        st.success(f"Usando la columna T del CTC: **{m_ctc_col}**")

        # Normalización y agrupado
        df_car["_id_norm"] = normalize_id(df_car[id_car])
        df_ctc["_id_norm"] = normalize_id(df_ctc[id_ctc])
        df_car["_monto"] = normalize_money(df_car[monto_car])
        df_ctc["_monto"] = normalize_money(df_ctc[m_ctc_col])

        car_group = df_car.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto": "monto_carrefour"})
        ctc_group = df_ctc.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto": "monto_ctc"})

        # Totales
        calculate_and_display_totals(car_group, ctc_group, 'monto_carrefour', 'monto_ctc', 'Carrefour', 'CTC')

        # Merge y diferencia por registro
        m = pd.merge(car_group, ctc_group, on="_id_norm", how="outer")
        m["diferencia"] = m["monto_carrefour"].fillna(0) - m["monto_ctc"].fillna(0)

        st.subheader("Conciliados por ID")
        st.dataframe(style_mismatches(m, 'diferencia'), height=400, use_container_width=True)
        
        # Descarga
        output = io.BytesIO()
        data_to_excel = {'Conciliados': m}
        output = get_excel_writer(data_to_excel, output)
        output.seek(0)
        
        st.download_button(
            label="Descargar conciliación Carrefour",
            data=output,
            file_name="conciliacion_Carrefour.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        st.info("Por favor, subí ambos archivos para iniciar la conciliación.")
















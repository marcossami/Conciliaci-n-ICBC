import streamlit as st
import pandas as pd
import io

st.set_page_config(page_title="Conciliación ICBC Mall", layout="wide")
st.title("Conciliación ICBC Mall")

uploaded_decidir = st.file_uploader("Sube el reporte de Decidir (.xlsx)", type="xlsx")
uploaded_aper    = st.file_uploader("Sube el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx")

if uploaded_decidir and uploaded_aper:
    # 1) Leer y filtrar sólo “Acreditada”
    df_dec = pd.read_excel(uploaded_decidir)
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

    # Columnas de fecha y monto limpio
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
    df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC")
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

    st.markdown(f"<h2>Total Decidir: {total_dec:,.2f}</h2>", unsafe_allow_html=True)
    st.markdown(f"<h2>Total Aper:    {total_ape:,.2f}</h2>", unsafe_allow_html=True)

    # Mostrar la diferencia SIN signo, usando su valor absoluto
    if diff_total == 0:
        resultado = "✅ Los montos coinciden"
        color = "green"
    elif diff_total > 0:
        resultado = f"❌ El monto de Decidir es mayor por {diff_abs:,.2f}"
        color = "red"
    else:
        resultado = f"❌ El monto de Aper es mayor por {diff_abs:,.2f}"
        color = "red"

    st.markdown(
        f"<h2 style='color:{color}'>Diferencia: {diff_abs:,.2f} — {resultado}</h2>",
        unsafe_allow_html=True
    )

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

    # 5a) Resaltar filas donde "diferencia" ≠ 0: fondo rojo y texto en negrita
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
    st.info("Por favor, sube ambos archivos para iniciar la conciliación.")































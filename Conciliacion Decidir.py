import streamlit as st
import pandas as pd
import numpy as np
import io
import re
import unicodedata
from pathlib import Path

# =========================
# CONFIG INICIAL
# =========================
st.set_page_config(page_title="Conciliador De Facturación Para Marketplaces Externos", layout="wide")
st.title("Conciliador De Facturación Para Marketplaces Externos")

# =========================
# SELECTOR
# =========================
OPTIONS = ["(seleccionar)", "ICBC Mall", "Carrefour"]
canal = st.selectbox("¿Qué marketplace querés conciliar?", OPTIONS, index=0)
if canal == "(seleccionar)":
    st.info("Elegí un canal para empezar.")
    st.stop()

# =========================
# HELPERS COMUNES
# =========================
def normalize_money(series: pd.Series, dash_as_zero: bool = False) -> pd.Series:
    s = series.astype(str).str.strip()
    if dash_as_zero:
        s = s.replace({r'^\s*[-–—]\s*$': '0'}, regex=True)
    s = s.str.replace(r'[^\d,.\-]', '', regex=True)

    def parse_one(x: str):
        if x == '' or x is None:
            return np.nan
        if ',' in x and '.' in x:
            if x.rfind(',') > x.rfind('.'):
                x = x.replace('.', '').replace(',', '.')
            else:
                x = x.replace(',', '')
        elif '.' in x:
            parts = x.rsplit('.', 1)
            if len(parts[-1]) == 3 and parts[0].replace('.', '').isdigit():
                x = x.replace('.', '')
        elif ',' in x:
            parts = x.rsplit(',', 1)
            if len(parts[-1]) == 3 and parts[0].replace(',', '').isdigit():
                x = x.replace(',', '')
            else:
                x = x.replace(',', '.')
        try:
            return float(x)
        except Exception:
            return np.nan

    return s.map(parse_one)


def format_ars_ctc(value) -> str:
    if pd.isna(value):
        return "—"
    v = int(round(float(value)))
    return "$" + f"{v:,}".replace(",", ".")


def only_digits_between_hyphens(series: pd.Series) -> pd.Series:
    s = series.astype(str).fillna('').str.strip()
    s = s.str.replace(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-', regex=True)
    s = s.str.replace(r'[\u00A0\u2007\u202F]', ' ', regex=True)
    mid = s.str.extract(r'(?i)[A-Za-z]+-(\d+)-', expand=False)
    fallback = s.str.extract(r'(\d{6,})', expand=False)
    res = mid.fillna(fallback)
    res = res.astype(str).str.replace(r'[^\d]', '', regex=True)
    res = res.replace({'': np.nan, 'nan': np.nan})
    return res


def only_digits_before_first_hyphen(series: pd.Series) -> pd.Series:
    """Devuelve los dígitos anteriores al primer guion (o el primer bloque numérico largo)."""
    s = series.astype(str).fillna('').str.strip()
    s = s.str.replace(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-', regex=True)
    s = s.str.replace(r'[\u00A0\u2007\u202F]', ' ', regex=True)
    before = s.str.extract(r'^(\d+)', expand=False)
    fallback = s.str.extract(r'(\d{6,})', expand=False)
    res = before.fillna(fallback)
    res = res.astype(str).str.replace(r'[^\d]', '', regex=True)
    res = res.replace({'': np.nan, 'nan': np.nan})
    return res


def dedupe_columns(cols) -> list:
    seen, out = {}, []
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


def excel_writer(output_buffer: io.BytesIO):
    try:
        import xlsxwriter  # noqa
        return pd.ExcelWriter(output_buffer, engine="xlsxwriter")
    except Exception:
        return pd.ExcelWriter(output_buffer, engine="openpyxl")


def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_col_by_keyword(df: pd.DataFrame, keywords: list) -> str:
    for col in df.columns:
        col_normalized = _norm(col)
        for keyword in keywords:
            if keyword in col_normalized:
                return col
    return None


def style_mismatch(row):
    cond = False
    try:
        if 'diferencia' in row.index:
            cond = (row['diferencia'] != 0) and pd.notna(row['diferencia'])
        elif 'diferencia_fmt' in row.index:
            s = str(row['diferencia_fmt']).replace("—", "").strip()
            s = re.sub(r'[^\d\-]', '', s)
            if s != '':
                try:
                    cond = int(s) != 0
                except Exception:
                    cond = False
        else:
            cond = False
    except Exception:
        cond = False
    return ['background-color: red; font-weight: bold;' if cond else '' for _ in row]


def read_file_robust(file_uploader, header_row: int = 0, prefer_sheet: str | None = None) -> pd.DataFrame:
    file_ext = Path(file_uploader.name).suffix.lower()
    if file_ext == '.csv':
        return pd.read_csv(file_uploader, encoding='utf-8', header=header_row, dtype=str)
    elif file_ext in ['.xlsx', '.xls']:
        raw = file_uploader.read()
        xls = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
        sheet_to_use = prefer_sheet if (prefer_sheet and prefer_sheet in xls.sheet_names) else xls.sheet_names[0]
        return pd.read_excel(io.BytesIO(raw), sheet_name=sheet_to_use, engine="openpyxl", header=header_row, dtype=str)
    else:
        st.error(f"Formato de archivo no soportado: {file_ext}")
        return pd.DataFrame()


# =========================
# FLOW ICBC (corregido: identificar columna 'carrito' adecuada)
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")

    tipo_conciliacion = st.radio("¿Qué tipo de conciliación querés hacer?", ["Transacciones", "Puntos"])

    if tipo_conciliacion == "Puntos":
        st.warning("🔧 La conciliación de puntos aún está en desarrollo.")
        return

    uploaded_decidir = st.file_uploader("Sube el reporte de Decidir (.xlsx)", type="xlsx", key="icbc_decidir")
    uploaded_aper = st.file_uploader("Sube el reporte de Aper (hoja ICBC) (.xlsx)", type="xlsx", key="icbc_aper")

    if not (uploaded_decidir and uploaded_aper):
        st.info("Por favor, sube ambos archivos para iniciar la conciliación.")
        return

    try:
        # 1) Leer y filtrar sólo “Acreditada”
        df_dec = pd.read_excel(uploaded_decidir, engine="openpyxl")
        df_dec.columns = [str(c).strip() for c in df_dec.columns]

        col_estado = get_col_by_keyword(df_dec, ["estado", "status"])
        if col_estado is None:
            st.error("El reporte de Decidir no contiene la columna 'estado' esperada.")
            return
        df_dec[col_estado] = df_dec[col_estado].astype(str).str.lower()
        df_dec = df_dec[df_dec[col_estado] == 'acreditada']

        # detectar columna que contiene el id oper en Decidir (lo usamos igual que antes)
        col_id_candidate = get_col_by_keyword(df_dec, ["id oper", "idoper", "id_oper", "id oper.", "id"])
        if col_id_candidate is None:
            first_col = df_dec.columns[0]
            col_id_candidate = first_col

        # Extraer idoper: TOMAR SÓLO LOS DÍGITOS HASTA EL PRIMER GUION
        df_dec['idoper'] = only_digits_before_first_hyphen(df_dec[col_id_candidate])

        # Columnas de fecha y monto limpio
        fecha_cols_dec = [c for c in df_dec.columns if 'fecha' in c.lower()]
        monto_col_dec = None
        for c in df_dec.columns:
            cl = c.lower()
            if 'monto' in cl or 'importe' in cl:
                monto_col_dec = c
                break
        if monto_col_dec is None:
            st.error("No se encontró columna de monto/importe en el reporte de Decidir.")
            return

        df_dec['monto_decidir'] = (
            df_dec[monto_col_dec].astype(str)
                .str.replace(r'[^\d,.-]', '', regex=True)
                .str.replace(',', '.', regex=False)
                .pipe(pd.to_numeric, errors='coerce')
        )

        agg_dec = {col: 'min' for col in fecha_cols_dec}
        agg_dec['monto_decidir'] = 'sum'
        dec_group = (
            df_dec
            .groupby('idoper', dropna=True)
            .agg(agg_dec)
            .reset_index()
        )
    except Exception as e:
        st.error(f"Ocurrió un error procesando el reporte de Decidir: {e}")
        return

    try:
        # 2) Leer y preparar Aper (hoja ICBC)
        df_ape = pd.read_excel(uploaded_aper, sheet_name="ICBC", engine="openpyxl")
        df_ape.columns = [str(c).strip() for c in df_ape.columns]

        # --- Nueva lógica: priorizar columna 'carrito'; si no existe, buscar columna tipo 'id oper' y tomar la columna a la derecha ---
        carrito_col = None
        # 1) buscar columna que contenga exactamente 'carrito' (normalizada) o la palabra
        for c in df_ape.columns:
            if _norm(c) == "carrito" or "carrito" in _norm(c):
                carrito_col = c
                break

        # 2) si no se encontró, buscar columna tipo 'id oper' / 'idoper' / 'numero de orden' y tomar la siguiente columna (derecha)
        if carrito_col is None:
            for idx, c in enumerate(df_ape.columns):
                n = _norm(c)
                if any(k in n for k in ['id oper', 'idoper', 'id_oper', 'id oper.', 'numero de orden', 'numero orden', 'nro cobro', 'nro. cobro', 'numero de cobro']):
                    # si existe columna a la derecha, la usamos como carrito (como me pediste)
                    if idx + 1 < len(df_ape.columns):
                        carrito_col = df_ape.columns[idx + 1]
                        break

        # 3) fallback: buscar cualquier columna que contenga la palabra 'carrito' (si no capturada por 1)
        if carrito_col is None:
            for c in df_ape.columns:
                if "carrito" in _norm(c):
                    carrito_col = c
                    break

        # 4) último recurso: buscar columnas que parezcan ID (números largos) y usar esa columna
        if carrito_col is None:
            for c in df_ape.columns:
                sample = df_ape[c].astype(str).dropna().head(10).astype(str).tolist()
                # si en la muestra hay strings con guiones y números al inicio, lo asumimos
                if any(re.match(r'^\d+\-', s) or re.search(r'\d{6,}', s) for s in sample):
                    carrito_col = c
                    break

        if carrito_col is None:
            st.error("No se encontró la columna 'CARRITO' en el reporte de Aper (hoja ICBC). Revisa el archivo.")
            return

        # Extraer carrito: tomar dígitos hasta el primer guion (como pediste)
        df_ape['carrito'] = only_digits_before_first_hyphen(df_ape[carrito_col])

        fecha_cols_ape = [c for c in df_ape.columns if 'fecha' in c.lower()]

        cost_col = None
        for c in df_ape.columns:
            cl = c.lower()
            if 'costo' in cl and 'producto' in cl:
                cost_col = c
                break
        if cost_col is None:
            for c in df_ape.columns:
                cl = c.lower()
                if 'importe' in cl or 'monto' in cl:
                    cost_col = c
                    break
        if cost_col is None:
            st.error("No se encontró columna 'costo producto' ni 'importe' en el reporte de Aper.")
            return

        df_ape['costoproducto'] = (
            df_ape[cost_col].astype(str)
                .str.replace(r'[^\d,.-]', '', regex=True)
                .str.replace(',', '.', regex=False)
                .pipe(pd.to_numeric, errors='coerce')
        )

        agg_ape = {col: 'min' for col in fecha_cols_ape}
        agg_ape['costoproducto'] = 'sum'
        ape_group = (
            df_ape
            .groupby('carrito', dropna=True)
            .agg(agg_ape)
            .reset_index()
        )
    except Exception as e:
        st.error(f"Ocurrió un error procesando el reporte de Aper: {e}")
        return

    # 3) Mostrar totales y diferencia global
    try:
        total_dec = dec_group['monto_decidir'].sum()
        total_ape = ape_group['costoproducto'].sum()
    except Exception as e:
        st.error(f"Error calculando totales: {e}")
        return

    diff_total = total_dec - total_ape
    diff_abs = abs(diff_total)

    st.markdown(f"<h3>Total Decidir: {total_dec:,.2f}</h3>", unsafe_allow_html=True)
    st.markdown(f"<h3>Total Aper:    {total_ape:,.2f}</h3>", unsafe_allow_html=True)

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
        f"<h3 style='color:{color}'>Diferencia: {diff_abs:,.2f} — {resultado}</h3>",
        unsafe_allow_html=True
    )

    # 4) Validar mutualidad de IDs
    set_dec = set(dec_group['idoper'])
    set_ape = set(ape_group['carrito'])
    falt_aper = sorted(set_dec - set_ape)
    falt_decider = sorted(set_ape - set_dec)
    if not falt_aper and not falt_decider:
        st.success("Todos los registros acreditados fueron encontrados correctamente.")
    else:
        if falt_aper:
            st.error("IDoper acreditadas que faltan en Aper: " + ", ".join(map(str, falt_aper)))
        if falt_decider:
            st.error("Carritos en Aper que no están en acreditadas de Decidir: " + ", ".join(map(str, falt_decider)))

    # 5) Conciliación y diferencia por registro (inner join)
    df_matched = pd.merge(
        dec_group, ape_group,
        left_on='idoper', right_on='carrito',
        how='inner',
        suffixes=('_dec', '_ape')
    )
    df_matched['diferencia'] = df_matched['monto_decidir'] - df_matched['costoproducto']

    final_cols = ['idoper', 'carrito'] + fecha_cols_dec + ['monto_decidir'] + fecha_cols_ape + ['costoproducto', 'diferencia']
    final_cols = [c for c in final_cols if c in df_matched.columns]

    df_result = df_matched[final_cols]

    def _style_mismatch_local(row):
        return ['background-color: red; font-weight: bold;' if row.get('diferencia', 0) != 0 else '' for _ in row]

    st.subheader("Registros Conciliados")
    st.dataframe(df_result.style.apply(_style_mismatch_local, axis=1), height=500)

    # 6) Mostrar no-matches
    st.subheader("Decidir acreditadas sin Aper")
    df_dec_sin = dec_group[~dec_group['idoper'].isin(ape_group['carrito'])]
    st.dataframe(df_dec_sin, height=200)

    st.subheader("Aper sin Decidir acreditadas")
    df_ape_sin = ape_group[~ape_group['carrito'].isin(dec_group['idoper'])]
    st.dataframe(df_ape_sin, height=200)

    # 7) Descargar Excel final
    try:
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
                if rows > 0 and cols > 0:
                    ws.conditional_format(1, 0, rows, cols - 1, {'type': 'no_blanks', 'format': yellow})
        output.seek(0)
        st.download_button(
            label="Descargar conciliación completa (ICBC)",
            data=output,
            file_name="conciliacion_ICBC.xlsx",
            mime="application/vnd.openxmlformats-officedocument-spreadsheetml.sheet"
        )
    except Exception as e:
        st.error(f"Error al generar el Excel de descarga: {e}")


# =========================
# FLOW CARREFOUR (SIN CAMBIOS)
# =========================
def run_carrefour():
    st.header("Carrefour Marketplace — CTC vs Carrefour")

    c1, c2 = st.columns(2)
    with c1:
        file_ctc = st.file_uploader("Subí **Reporte CTC** (.xlsx, .csv)", type=["xlsx", "csv"], key="ctc_rep")
    with c2:
        file_carrefour_list = st.file_uploader(
            "Subí los **reportes Carrefour** (.xlsx, .csv) - Podes subir varios",
            type=["xlsx", "csv"],
            accept_multiple_files=True,
            key="carrefour_files"
        )

    if not (file_ctc and file_carrefour_list):
        st.info("Subí ambos archivos para iniciar la conciliación.")
        return

    # Leer y unir archivos Carrefour (usar hoja MP si existe)
    try:
        df_car_list = []
        for f in file_carrefour_list:
            ext = Path(f.name).suffix.lower()
            if ext in ['.xlsx', '.xls']:
                raw = f.read()
                xls = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
                sheet_to_use = "MP" if "MP" in xls.sheet_names else xls.sheet_names[0]
                df_tmp = pd.read_excel(io.BytesIO(raw), sheet_name=sheet_to_use, engine="openpyxl", header=0, dtype=str)
            else:
                df_tmp = pd.read_csv(f, encoding='utf-8', header=0, dtype=str)
            df_car_list.append(df_tmp)
        df_carrefour = pd.concat(df_car_list, ignore_index=True)
        df_carrefour.columns = dedupe_columns(df_carrefour.columns)
    except Exception as e:
        st.error(f"Error al leer los archivos Carrefour. Detalle: {e}")
        return

    # Leer reporte CTC con header=9 (fila 10 como nombres de columna)
    try:
        raw = file_ctc.read()
        xls = pd.ExcelFile(io.BytesIO(raw), engine="openpyxl")
        sheet_to_use = xls.sheet_names[0]
        df_ctc = pd.read_excel(io.BytesIO(raw), sheet_name=sheet_to_use, engine="openpyxl", header=9, dtype=str)
        df_ctc.columns = dedupe_columns(df_ctc.columns)
    except Exception as e:
        st.error(f"Error al leer el archivo CTC. Detalle: {e}")
        return

    # detectar columnas clave
    col_id_ctc = get_col_by_keyword(df_ctc, ["id venta", "numero de orden", "orden", "id", "order"])
    col_m_ctc = get_col_by_keyword(df_ctc, ["pvp total c/iva", "importe total", "monto", "importe"])

    # forzar uso de columna 'Order' EXACTA en el archivo Carrefour si existe (normalizada)
    forced_order_col = None
    for c in df_carrefour.columns:
        if _norm(c) == "order":
            forced_order_col = c
            break
    if forced_order_col is not None:
        col_id_car = forced_order_col
    else:
        col_id_car = get_col_by_keyword(df_carrefour, ["order", "numero de orden", "nro. cobro", "orden", "id", "numero orden"])

    col_m_car = get_col_by_keyword(df_carrefour, ["importe total", "importe", "monto", "importe no an"])

    if not col_id_ctc or not col_m_ctc:
        st.error("No se encontraron 'ID Venta' o 'PVP TOTAL C/IVA' en el reporte CTC. Revisa columnas y formato.")
        return

    if not col_id_car or not col_m_car:
        st.error("No se encontraron las columnas 'Order/Numero de Orden' o 'Importe Total' en el/los reporte(s) Carrefour.")
        return

    # ---------- CTC: extraer número entre guiones ----------
    try:
        df_ctc['_id_raw'] = df_ctc[col_id_ctc].astype(str)
        df_ctc['_id_norm'] = only_digits_between_hyphens(df_ctc['_id_raw'])
        df_ctc['_monto'] = normalize_money(df_ctc[col_m_ctc])
        ctc_group = df_ctc.groupby('_id_norm', dropna=True)['_monto'].sum().reset_index().rename(columns={'_monto': 'monto_ctc'})
    except Exception as e:
        st.error(f"Error procesando el archivo CTC. Detalle: {e}")
        return

    # ---------- Carrefour: extraer número HASTA el primer guion desde la columna Order ----------
    try:
        df_carrefour['_raw_importe'] = df_carrefour[col_m_car]
        df_carrefour['_monto'] = normalize_money(df_carrefour[col_m_car], dash_as_zero=True)
        df_carrefour['_id_raw'] = df_carrefour[col_id_car].astype(str)
        df_carrefour['_id_norm'] = only_digits_before_first_hyphen(df_carrefour['_id_raw'])
        missing_mask = df_carrefour['_id_norm'].isna()
        if missing_mask.any():
            df_carrefour.loc[missing_mask, '_id_norm'] = df_carrefour.loc[missing_mask, '_id_raw'].str.extract(r'(\d{6,})', expand=False)

        df_carrefour['_id_for_group'] = df_carrefour['_id_norm'].fillna('__NO_ID__')
        grouped = df_carrefour.groupby('_id_for_group', dropna=False)['_monto'].sum().reset_index().rename(columns={'_id_for_group': '_id_norm', '_monto': 'monto_carrefour'})
        grouped['_id_norm'] = grouped['_id_norm'].replace({'__NO_ID__': np.nan})
        carrefour_group = grouped[['_id_norm', 'monto_carrefour']]
    except Exception as e:
        st.error(f"Error procesando el/los archivo(s) Carrefour. Detalle: {e}")
        return

    # Normalización final de IDs (solo dígitos) antes del merge
    def _normalize_id_for_merge(col: pd.Series) -> pd.Series:
        s = col.copy()
        s = s.where(pd.notna(s), other=np.nan)
        s = s.astype(str).str.strip()
        s = s.replace(r'^(nan|none|NaN|None)$', '', regex=True)
        s = s.str.replace(r'[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]', '-', regex=True)
        s = s.str.replace(r'[\u00A0\u2007\u202F]', ' ', regex=True)
        digits = s.str.extract(r'(\d{6,})', expand=False)
        out = digits.fillna(s.str.replace(r'\s+', '', regex=True))
        out = out.astype(str).str.replace(r'[^0-9]', '', regex=True)
        out = out.replace({'': np.nan, 'nan': np.nan})
        return out.astype('object')

    if '_id_norm' in carrefour_group.columns:
        carrefour_group['_id_norm'] = _normalize_id_for_merge(carrefour_group['_id_norm'])
    else:
        st.error("carrefour_group no contiene '_id_norm' — revisar bloque Carrefour.")
        return

    if '_id_norm' in ctc_group.columns:
        ctc_group['_id_norm'] = _normalize_id_for_merge(ctc_group['_id_norm'])
    else:
        st.error("ctc_group no contiene '_id_norm' — revisar bloque CTC.")
        return

    # Realizar merges: full y matched (inner)
    try:
        m_all = pd.merge(carrefour_group, ctc_group, on="_id_norm", how="outer")
        m_all["monto_carrefour"] = m_all.get("monto_carrefour", 0)
        if isinstance(m_all["monto_carrefour"], pd.Series):
            m_all["monto_carrefour"] = m_all["monto_carrefour"].fillna(0)
        m_all["monto_ctc"] = m_all.get("monto_ctc", 0)
        if isinstance(m_all["monto_ctc"], pd.Series):
            m_all["monto_ctc"] = m_all["monto_ctc"].fillna(0)

        m_matched = pd.merge(carrefour_group, ctc_group, on="_id_norm", how="inner")
        if "monto_carrefour" not in m_matched.columns:
            m_matched["monto_carrefour"] = 0
        if "monto_ctc" not in m_matched.columns:
            m_matched["monto_ctc"] = 0
        m_matched["diferencia"] = m_matched["monto_carrefour"].astype(float).fillna(0) - m_matched["monto_ctc"].astype(float).fillna(0)
    except Exception as e:
        st.error(f"Error al conciliar por ID. Detalle: {e}")
        return

    # Métricas basadas SOLO en matched
    total_ctc_matched = m_matched["monto_ctc"].sum(skipna=True)
    total_car_matched = m_matched["monto_carrefour"].sum(skipna=True)
    diff_total_matched = total_car_matched - total_ctc_matched
    diff_abs_matched = abs(diff_total_matched)

    # Métricas globales (todos los IDs)
    total_ctc_all = ctc_group["monto_ctc"].sum(skipna=True)
    total_car_all = carrefour_group["monto_carrefour"].sum(skipna=True)
    diff_total_all = total_car_all - total_ctc_all
    diff_abs_all = abs(diff_total_all)

    st.subheader("Comparación De Monto total (solo para ID en ambos)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total CTC (IDs en ambos)", format_ars_ctc(total_ctc_matched))
    c2.metric("Total Carrefour (IDs en ambos)", format_ars_ctc(total_car_matched))
    c3.metric("Diferencia (ambos)", format_ars_ctc(diff_abs_matched), delta=format_ars_ctc(diff_total_matched))
    st.info("Las métricas anteriores se calculan solo con los IDs que aparecen en ambos reportes (intersección).")

    st.subheader("Comparación De Monto total Global")
    g1, g2, g3 = st.columns(3)
    g1.metric("Total CTC (global)", format_ars_ctc(total_ctc_all))
    g2.metric("Total Carrefour (global)", format_ars_ctc(total_car_all))
    g3.metric("Diferencia (global)", format_ars_ctc(diff_abs_all), delta=format_ars_ctc(diff_total_all))
    st.info("Estas métricas consideran todos los registros por archivo, sin filtrar por matching.")

    # Mostrar la tabla de diferencias SOLO para matched (si hay)
    m_show = m_matched.copy()
    m_show["monto_carrefour_fmt"] = m_show["monto_carrefour"].map(format_ars_ctc)
    m_show["monto_ctc_fmt"] = m_show["monto_ctc"].map(format_ars_ctc)
    m_show["diferencia_fmt"] = m_show["diferencia"].map(format_ars_ctc)

    st.subheader("Conciliación por ID (solo IDs encontrados en ambos reportes)")
    if m_show.empty:
        st.warning("No se encontraron IDs presentes en ambos reportes — la tabla de conciliación por ID está vacía.")
    if "diferencia" in m_show.columns and not m_show.empty:
        display_df = m_show.sort_values("diferencia", na_position='last')[["_id_norm", "monto_carrefour_fmt", "monto_ctc_fmt", "diferencia_fmt"]]
    else:
        display_df = m_show[["_id_norm", "monto_carrefour_fmt", "monto_ctc_fmt", "diferencia_fmt"]]
    st.dataframe(display_df.style.apply(style_mismatch, axis=1), height=480)

    # IDs presentes/ausentes
    ids_ctc = set(ctc_group["_id_norm"].dropna())
    ids_car = set(carrefour_group["_id_norm"].dropna())
    solo_ctc = sorted(ids_ctc - ids_car)
    solo_car = sorted(ids_car - ids_ctc)

    st.subheader("IDs en CTC y no en Carrefour")
    st.write(", ".join(map(str, solo_ctc)) if solo_ctc else "— Ninguno —")
    st.subheader("IDs en Carrefour y no en CTC")
    st.write(", ".join(map(str, solo_car)) if solo_car else "— Ninguno —")

    # Descarga: incluyo matched y full (m_all)
    out = io.BytesIO()
    with excel_writer(out) as writer:
        m_matched.to_excel(writer, sheet_name="Conciliados_matched", index=False)
        m_all.to_excel(writer, sheet_name="Conciliados_full", index=False)
        pd.DataFrame({"id_solo_ctc": solo_ctc}).to_excel(writer, sheet_name="CTC_sin_Carrefour", index=False)
        pd.DataFrame({"id_solo_carrefour": solo_car}).to_excel(writer, sheet_name="Carrefour_sin_CTC", index=False)
    out.seek(0)
    st.download_button("Descargar conciliación Carrefour (matched + full)", out, "conciliacion_Carrefour.xlsx",
                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# =========================
# ROUTER
# =========================
if canal == "ICBC Mall":
    run_icbc()
elif canal == "Carrefour":
    run_carrefour()






































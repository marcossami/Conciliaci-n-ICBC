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
# DESPLEGABLE INICIAL
# =========================
OPTIONS = ["(seleccionar)", "ICBC Mall", "Carrefour MKP"]
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

# =========================
# ICBC (igual que antes, resumido)
# =========================
def run_icbc():
    st.header("ICBC Mall — Decidir vs Aper")
    st.info("Lógica ICBC intacta aquí...")  # dejo corto para enfocarnos en Carrefour

# =========================
# CARREFOUR
# =========================
def run_carrefour():
    st.header("Carrefour Marketplace — CTC vs Carrefour")

    c1, c2 = st.columns(2)
    with c1:
        file_no_ctc = st.file_uploader("Subí Reporte de Carrefour", type=["xlsx"], key="carrefour_rep")
    with c2:
        file_ctc    = st.file_uploader("Subí Reporte CTC", type=["xlsx"], key="ctc_rep")
    

    if file_ctc and file_no_ctc:
        # ---------- CTC ----------
        df_ctc = pd.read_excel(file_ctc, engine="openpyxl")
        df_ctc.columns = dedupe_columns(df_ctc.columns)
        col_id_ctc = df_ctc.columns[0]   # Col A: ID Venta
        col_m_ctc  = df_ctc.columns[19]  # Col T: monto
        df_ctc["_id_norm"] = ctc_id_norm(df_ctc[col_id_ctc])
        df_ctc["_monto"]   = normalize_money(df_ctc[col_m_ctc])
        ctc_group = df_ctc.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto":"monto_ctc"})

        # ---------- NO CTC ----------
        df_no = pd.read_excel(file_no_ctc, engine="openpyxl")
        df_no.columns = dedupe_columns(df_no.columns)
        col_id_no = df_no.columns[1]   # Col B: Numero de Orden
        col_m_no  = df_no.columns[8]   # Col I: Importe Total
        df_no["_id_norm"] = carrefour_id_norm(df_no[col_id_no])
        df_no["_monto"]   = normalize_money(df_no[col_m_no], dash_as_zero=True)
        no_group = df_no.groupby("_id_norm", dropna=True)["_monto"].sum().reset_index().rename(columns={"_monto":"monto_no_ctc"})

        # ---------- Conciliación ----------
        ids_ctc = set(ctc_group["_id_norm"].dropna())
        ids_no  = set(no_group["_id_norm"].dropna())
        solo_ctc = sorted(ids_ctc - ids_no)
        solo_no  = sorted(ids_no - ids_ctc)

        st.subheader("IDs en CTC y no en NO CTC")
        st.write(", ".join(map(str, solo_ctc)) if solo_ctc else "— Ninguno —")
        st.subheader("IDs en NO CTC y no en CTC")
        st.write(", ".join(map(str, solo_no)) if solo_no else "— Ninguno —")

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
        c2.metric("Total NO CTC (Importe Total)", f"{total_no:,.2f}")
        c3.metric("Diferencia abs.", f"{diff_abs:,.2f}", delta=f"{diff_total:,.2f}")
        st.info(resumen)

        m = pd.merge(no_group, ctc_group, on="_id_norm", how="outer").fillna(0)
        m["diferencia"] = m["monto_no_ctc"] - m["monto_ctc"]

        def style_mismatch(row):
            return ['background-color: red; font-weight: bold;' if row['diferencia'] != 0 else '' for _ in row]

        st.subheader("Conciliación por ID (NO CTC - CTC)")
        st.dataframe(m.style.apply(style_mismatch, axis=1), height=480)

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




































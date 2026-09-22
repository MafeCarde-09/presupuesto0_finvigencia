# -*- coding: utf-8 -*-
"""
Carga de datos desde Google Sheets
"""
import pandas as pd
import streamlit as st
from config import SHEET_ID, SHEET_NAME_DATOS, SHEET_NAME_FECHA_CORTE


def gsheet_csv_url(sheet_id: str, sheet_name: str) -> str:
    """Genera URL para leer Google Sheet como CSV"""
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={sheet_name}"


@st.cache_data(ttl=1800, show_spinner=False)
def load_cutoff_date(sheet_id: str = SHEET_ID,
                     sheet_name: str = SHEET_NAME_FECHA_CORTE) -> pd.Timestamp:
    """
    Carga fecha de corte desde Hoja2.

    Args:
        sheet_id: ID del Google Sheet
        sheet_name: Nombre de la hoja (por defecto Hoja2)

    Returns:
        pd.Timestamp con la fecha de corte
    """
    url = gsheet_csv_url(sheet_id, sheet_name)

    try:
        df = pd.read_csv(url, header=None)
        raw = str(df.iloc[0, 0]).strip() if not df.empty else ""

        # Parsear fecha con formato colombiano (día primero)
        ts = pd.to_datetime(raw, dayfirst=True, errors='coerce')

        if pd.isna(ts):
            st.warning(f"⚠️ Fecha inválida en {sheet_name}: '{raw}'. Usando fecha actual.")
            ts = pd.Timestamp.today().normalize()

        return pd.Timestamp(ts.date())

    except Exception as e:
        st.warning(f"⚠️ No se pudo cargar la fecha de corte ({e}). Usando fecha actual.")
        return pd.Timestamp.today().normalize()


@st.cache_data(ttl=1800, show_spinner=False)
def load_data(sheet_id: str = SHEET_ID,
              sheet_name: str = SHEET_NAME_DATOS) -> pd.DataFrame:
    """
    Carga datos principales desde Hoja1.

    Args:
        sheet_id: ID del Google Sheet
        sheet_name: Nombre de la hoja (por defecto Hoja1)

    Returns:
        DataFrame con datos normalizados, o DataFrame vacío si hay error temporal.
    """
    url = gsheet_csv_url(sheet_id, sheet_name)

    try:
        df = pd.read_csv(url)

        if df.empty:
            st.error(f"❌ {sheet_name} está vacía. Verifica los datos en Google Sheets.")
            st.stop()

        return df

    except Exception as e:
        st.error(
            f"❌ Error cargando datos desde {sheet_name}: {e}\n\n"
            "Intenta recargar la página en unos segundos."
        )
        st.stop()

# -*- coding: utf-8 -*-
"""
Procesamiento y normalización de datos
"""
import re
import pandas as pd
import numpy as np
from config import DATE_PARSE_DAYFIRST


def parse_number_co(series: pd.Series) -> pd.Series:
    """
    Parsea números en formato colombiano (1.234.567,89)
    """
    s = series.astype(str)
    s = s.str.replace(r"[^\d,.\-]", "", regex=True)
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")

# ==================== MESES EN ESPAÑOL ====================
MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def parse_mes_yyyy_es(serie: pd.Series) -> pd.Series:
    """Convierte texto 'AAAA mes_español' (ej. '1900 enero') -> Timestamp(dia=1)."""
    def _parse_one(valor):
        if pd.isna(valor):
            return pd.NaT
        texto = str(valor).strip().lower()
        match = re.match(r'(\d{4})\s+([a-záéíóúñ]+)', texto)
        if not match:
            return pd.NaT
        anio_str, mes_str = match.groups()
        mes_num = MESES_ES.get(mes_str)
        if mes_num is None:
            return pd.NaT
        return pd.Timestamp(year=int(anio_str), month=mes_num, day=1)
    return serie.apply(_parse_one)


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parsea y normaliza columna de fechas.
    """
    df = df.copy()
    
    if 'MES_TXT' in df.columns:
        df['FECHA'] = pd.to_datetime(
            df['MES_TXT'], 
            dayfirst=DATE_PARSE_DAYFIRST,
            errors='coerce'
        )

        # Fallback: para lo que no se pudo convertir, reintentar como "AAAA mes_español"
        faltantes = df['FECHA'].isna() & df['MES_TXT'].notna()
        if faltantes.any():
            df.loc[faltantes, 'FECHA'] = parse_mes_yyyy_es(df.loc[faltantes, 'MES_TXT'])

    elif 'ANIO' in df.columns and 'MES' in df.columns:
        try:
            df['FECHA'] = pd.to_datetime(
                dict(
                    year=df['ANIO'].astype(int),
                    month=df['MES'].astype(int),
                    day=1
                ),
                errors='coerce'
            )
        except Exception:
            df['FECHA'] = pd.NaT
    elif 'ANIO' in df.columns:
        df['FECHA'] = pd.to_datetime(
            df['ANIO'].astype(str) + "-01-01",
            errors='coerce'
        )
    else:
        df['FECHA'] = pd.NaT
    
    df['FECHA'] = df['FECHA'].apply(
        lambda x: pd.Timestamp(year=x.year, month=x.month, day=1) 
        if pd.notna(x) else pd.NaT
    )
    
    return df

def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza nombres de columnas y tipos de datos.
    """
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]
    
    rename_map = {
        'Año': 'ANIO',
        'ANO': 'ANIO',
        'YEAR': 'ANIO',
        'Mes yyyy': 'MES_TXT',
        'MES YYYY': 'MES_TXT',
        'Mes': 'MES_TXT',
        'MES': 'MES_TXT',
        'Codigo y Sucursal': 'SUCURSAL',
        'Código y Sucursal': 'SUCURSAL',
        'Linea': 'LINEA',
        'Línea': 'LINEA',
        'Linea +': 'LINEA_PLUS',
        'Línea +': 'LINEA_PLUS',
        'LINEA +': 'LINEA_PLUS',
        'Compañía': 'COMPANIA',
        'COMPAÑÍA': 'COMPANIA',
        'Imp Prima': 'IMP_PRIMA',
        'Imp Prima Cuota': 'PRESUPUESTO',
        'Código y Ramo': 'CODIGO_RAMO',
        'Codigo y Ramo': 'CODIGO_RAMO'
    }
    
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df = parse_dates(df)
    
    if 'IMP_PRIMA' in df.columns:
        df['IMP_PRIMA'] = parse_number_co(df['IMP_PRIMA'])
    
    if 'PRESUPUESTO' not in df.columns and 'IMP_PRIMA_CUOTA' in df.columns:
        df['PRESUPUESTO'] = parse_number_co(df['IMP_PRIMA_CUOTA'])
    elif 'PRESUPUESTO' in df.columns:
        df['PRESUPUESTO'] = parse_number_co(df['PRESUPUESTO'])
    
    for col in ['SUCURSAL', 'LINEA', 'LINEA_PLUS', 'COMPANIA', 'CODIGO_RAMO']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    
    if 'CODIGO_RAMO' in df.columns and 'RAMO' not in df.columns:
        df['RAMO'] = df['CODIGO_RAMO']
    
    if 'ANIO' not in df.columns and 'FECHA' in df.columns:
        df['ANIO'] = df['FECHA'].dt.year
    
    df = df.dropna(subset=['FECHA'])
    
    return df

#---------------------------------------------------------------
#         NORMALIZACIÓN FUENTE 2 - FECHA FIN VIGENCIA
#---------------------------------------------------------------
def normalize_dataframe_fuente2(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza la nueva base (Año, Mes yyyy, Codigo y Sucursal, Linea, Imp Prima, Linea +)."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    rename_map = {
        'Año': 'ANIO',
        'Mes yyyy': 'MES_TXT',
        'Codigo y Sucursal': 'SUCURSAL',
        'Linea': 'LINEA',
        'Linea +': 'LINEA_PLUS',
        'Imp Prima': 'IMP_PRIMA',
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df = parse_dates(df)  
    
    if 'IMP_PRIMA' in df.columns:
        df['IMP_PRIMA'] = parse_number_co(df['IMP_PRIMA'])

    for col in ['SUCURSAL', 'LINEA', 'LINEA_PLUS']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    if 'ANIO' not in df.columns and 'FECHA' in df.columns:
        df['ANIO'] = df['FECHA'].dt.year
    
    df['FUENTE'] = 'fuente2'
    df = df.dropna(subset=['FECHA'])
    return df

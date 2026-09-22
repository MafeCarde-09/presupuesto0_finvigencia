# -*- coding: utf-8 -*-
"""
AseguraView · Primas & Presupuesto
Aplicación Streamlit refactorizada y modular
"""
import warnings
warnings.filterwarnings("ignore")

import base64
import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import html
from io import BytesIO
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill
from openpyxl.utils import get_column_letter

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    st.error("❌ Dependencia faltante: `plotly`. Ejecuta `pip install -r requirements.txt` y reinicia la app.")
    st.stop()

# Configuración
from config import PAGE_TITLE, PAGE_ICON, LAYOUT, LEY_GARANTIAS_2026

# Utils
from utils.data_loader import load_data, load_cutoff_date
from utils.data_processor import normalize_dataframe
from utils.formatters import fmt_cop, badge_pct_html, badge_growth_html
from utils.date_utils import business_days_left
from utils.distribution import (
    MONTH_ABBR,
    MONTH_HEADER,
    append_distribution_totals,
    build_distribution_html,
    build_monthly_distribution,
)

# Models
from modelos.forecast_engine import ForecastEngine
from modelos.fianzas_adjuster import FianzasAdjuster
from modelos.budget_2026 import Budget2026Generator

# Components
from componentes.sidebar import render_sidebar
from componentes.tables import df_to_html
from componentes.charts import render_forecast_chart

# ==================== CONSTANTS ====================
# Indicadores visuales para el gráfico de ritmo comercial por sucursal
_INDICADOR_BUEN_RITMO = "🐰⚡"   # cumplimiento_ritmo >= 90%
_INDICADOR_RITMO_LENTO = "🐢"    # cumplimiento_ritmo < 90%
_UMBRAL_BUEN_RITMO = 90          # % mínimo para considerar buen ritmo
_UMBRAL_RITMO_MEDIO = 80         # % mínimo para naranja (ritmo medio)
_COLOR_BUEN_RITMO = '#16a34a'    # verde
_COLOR_RITMO_MEDIO = '#f59e0b'   # naranja
_COLOR_RITMO_LENTO = '#ef4444'   # rojo
_HEATMAP_MIN_BLEND_RATIO = 0.2
_HEATMAP_BLEND_RANGE = 0.8
_DETAILED_CHART_HEIGHT = 500
_DETAILED_FORECAST_CACHE_TTL_SECONDS = 3600
_DATA_CACHE_MAX_ENTRIES = 50
_INCREMENT_PCT_HIGH_THRESHOLD = 50
_INCREMENT_PCT_MEDIUM_THRESHOLD = 25
_MAX_DISTRIBUTION_CACHE_SIZE = 12


def _fragment_compat(func):
    """Compatibilidad con Streamlit fragment sin romper entornos viejos."""
    fragment_fn = getattr(st, "fragment", None)
    return fragment_fn(func) if callable(fragment_fn) else func


def _hex_to_rgba(hex_color: str, alpha: float = 0.1) -> str:
    """Convierte color hexadecimal a cadena rgba() para Plotly."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f'rgba({r},{g},{b},{alpha})'


def _blend_hex(start_hex: str, end_hex: str, ratio: float) -> str:
    """Interpola dos colores hexadecimales para construir gradientes suaves."""
    ratio = min(max(ratio, 0.0), 1.0)
    start = tuple(int(start_hex[i:i + 2], 16) for i in (1, 3, 5))
    end = tuple(int(end_hex[i:i + 2], 16) for i in (1, 3, 5))
    mixed = tuple(int(start[idx] + (end[idx] - start[idx]) * ratio) for idx in range(3))
    return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"


def _heatmap_cell_tokens(
    value: float,
    max_positive: float,
    max_negative: float = 0.0,
    is_total: bool = False,
    highlight_negative: bool = False,
) -> tuple[str, str, str]:
    """Devuelve fondo, color de texto y borde para una celda del mapa.

    Usa escala roja para valores positivos. Cuando ``highlight_negative`` es
    verdadero, usa una escala verde para valores negativos basada en
    ``max_negative``; en los demás casos deja valores no positivos en crema.
    """
    value = float(value)
    if value > 0:
        ratio = min(value / max_positive, 1.0) if max_positive > 0 else 0.0
        accent = _blend_hex(
            "#f87171" if is_total else "#e53e2f",
            "#5c0a04",
            _HEATMAP_MIN_BLEND_RATIO + ratio * _HEATMAP_BLEND_RANGE,
        )
        background = (
            f"linear-gradient(135deg, {_hex_to_rgba(accent, 0.94)}, "
            f"{_hex_to_rgba('#7f1d1d', 0.98)})"
        )
        text_color = "#fff7ed"
        border_color = "rgba(255,255,255,0.12)"
    elif highlight_negative and value < 0:
        ratio = min(abs(value) / max_negative, 1.0) if max_negative > 0 else 0.0
        accent = _blend_hex(
            "#4ade80" if is_total else "#16a34a",
            "#14532d",
            _HEATMAP_MIN_BLEND_RATIO + ratio * _HEATMAP_BLEND_RANGE,
        )
        background = (
            f"linear-gradient(135deg, {_hex_to_rgba(accent, 0.92)}, "
            f"{_hex_to_rgba('#14532d', 0.97)})"
        )
        text_color = "#f0fdf4"
        border_color = "rgba(255,255,255,0.14)"
    else:
        base = "#fff1e4" if is_total else "#fff8f0"
        background = (
            f"linear-gradient(135deg, {_hex_to_rgba(base, 0.98)}, "
            f"{_hex_to_rgba('#fde7d3', 0.94)})"
        )
        text_color = "#1f2937"
        border_color = "rgba(15,23,42,0.08)"
    return background, text_color, border_color


HEATMAP_TOTAL_ROW_LABELS = {'TOTAL', 'TOTAL LÍNEA'}
HEATMAP_ROUNDING_TOLERANCE = 1e-6


def _build_heatmap_html(
    pivot_deficit_detalle: pd.DataFrame,
    totales_linea: pd.Series,
    vista_mes: str,
    periodo_actual: pd.Timestamp,
    title_text: str,
    legend_text: str,
    note_text: str,
    highlight_negative: bool = False,
) -> str:
    """Construye el HTML de un mapa de calor con totales por línea.

    Recibe el detalle por sucursal, la fila de totales, los textos visibles del
    banner y una bandera para colorear valores negativos en verde cuando la
    métrica así lo requiera.
    """
    columnas = list(pivot_deficit_detalle.columns)
    if totales_linea.empty:
        total_values = pd.Series(dtype=float)
    else:
        total_values = pd.to_numeric(totales_linea, errors='coerce').fillna(0.0)

    if pivot_deficit_detalle.empty:
        detail_values = np.array([0.0], dtype=float)
    else:
        detail_values = pivot_deficit_detalle.to_numpy(dtype=float).ravel()
    combined_values = np.concatenate([detail_values, total_values.to_numpy()]) if not total_values.empty else detail_values
    positivos = [v for v in combined_values.astype(float) if v > 0]
    negativos = [abs(v) for v in combined_values.astype(float) if v < 0]
    max_positive = max(positivos, default=1.0)
    max_negative = max(negativos, default=1.0)
    grid_style = f"grid-template-columns:minmax(190px,1.35fr) repeat({len(columnas)}, minmax(120px,1fr));"

    html_parts = [
        '<div class="heatmap-shell">',
        (
            '<div class="heatmap-banner">'
            f'<div class="heatmap-title">{html.escape(title_text)} — {html.escape(vista_mes)} | {html.escape(periodo_actual.strftime("%m/%Y"))}</div>'
            f'<div class="heatmap-legend">{html.escape(legend_text)}</div>'
            '</div>'
        ),
        f'<div class="heatmap-grid" style="{grid_style}">',
        '<div class="heatmap-total-label">Totales por línea</div>',
    ]

    for linea in columnas:
        value = float(total_values.get(linea, 0.0))
        background, text_color, border_color = _heatmap_cell_tokens(
            value,
            max_positive,
            max_negative=max_negative,
            is_total=True,
            highlight_negative=highlight_negative,
        )
        positive_class = " heatmap-total-positive" if value > 0 else ""
        html_parts.append(
            (
                f'<div class="heatmap-total-cell{positive_class}" '
                f'style="background:{background};color:{text_color};border-color:{border_color};">'
                f'<div class="heatmap-total-caption">{html.escape(str(linea))}</div>'
                f'<div class="heatmap-total-value">{html.escape(fmt_cop(value))}</div>'
                '</div>'
            )
        )

    html_parts.append('<div class="heatmap-corner-label">Sucursal</div>')
    for linea in columnas:
        html_parts.append(f'<div class="heatmap-col-head">{html.escape(str(linea))}</div>')

    for sucursal, row in pivot_deficit_detalle.iterrows():
        html_parts.append(f'<div class="heatmap-row-label">{html.escape(str(sucursal))}</div>')
        for linea in columnas:
            value = float(row[linea])
            background, text_color, border_color = _heatmap_cell_tokens(
                value,
                max_positive,
                max_negative=max_negative,
                highlight_negative=highlight_negative,
            )
            positive_class = " heatmap-cell-positive" if value > 0 else ""
            html_parts.append(
                (
                    f'<div class="heatmap-cell{positive_class}" '
                    f'style="background:{background};color:{text_color};border-color:{border_color};">'
                    f'{html.escape(fmt_cop(value))}'
                    '</div>'
                )
            )

    html_parts.extend([
        '</div>',
        f'<div class="heatmap-note">{html.escape(note_text)}</div>',
        '</div>',
    ])
    return ''.join(html_parts)


def _build_branch_heatmap_data(
    df_filtered: pd.DataFrame,
    df_resumen: pd.DataFrame,
    metric_col: str,
    vista_mes: str,
    periodo_actual: pd.Timestamp,
    meses_quarter: list[int],
    ref_year: int,
    fecha_corte: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Distribuye una métrica de línea hacia sucursal según el peso presupuestal.

    Toma la métrica ya calculada en ``df_resumen`` para cada ``LINEA_PLUS`` y la
    reparte entre las combinaciones ``Suc_agrupada`` × ``LINEA_PLUS`` usando
    ``PRESUPUESTO`` como ponderador. Devuelve el detalle ordenado por faltante
    total descendente y una segunda tabla lista para exportación con la fila
    ``TOTAL LÍNEA`` agregada al final.
    """
    # ========== 1. OBTENER MÉTRICA TOTAL POR LÍNEA ==========
    df_res_sin_total = df_resumen.copy()
    
    # Validar columnas necesarias
    if 'LINEA_PLUS' not in df_res_sin_total.columns or metric_col not in df_res_sin_total.columns:
        return pd.DataFrame(), pd.DataFrame()

    # Filtrar filas de total
    df_res_sin_total = df_res_sin_total[df_res_sin_total['LINEA_PLUS'].notna()].copy()
    df_res_sin_total = df_res_sin_total[
        ~df_res_sin_total['LINEA_PLUS'].astype(str).str.upper().isin({'TOTAL', 'TOTAL LÍNEA'})
    ]
    
    if df_res_sin_total.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Convertir métrica a numérico
    df_res_sin_total[metric_col] = pd.to_numeric(df_res_sin_total[metric_col], errors='coerce').fillna(0.0)
    
    # ✅ TOTAL POR LÍNEA (este es el valor que hay que distribuir)
    metric_total_por_linea = df_res_sin_total.groupby('LINEA_PLUS', dropna=False)[metric_col].sum()

    # ========== 2. OBTENER PRESUPUESTO POR SUCURSAL × LÍNEA ==========
    if vista_mes == "Mes":
        df_pres_suc = df_filtered[
            (df_filtered['FECHA'] == periodo_actual) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].groupby(['Suc_agrupada', 'LINEA_PLUS'], dropna=False)['PRESUPUESTO'].sum().reset_index()
    elif vista_mes == "Año":
        df_pres_suc = df_filtered[
            (df_filtered['FECHA'].dt.year == ref_year) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].groupby(['Suc_agrupada', 'LINEA_PLUS'], dropna=False)['PRESUPUESTO'].sum().reset_index()
    else:
        df_pres_suc = df_filtered[
            (df_filtered['FECHA'].dt.year == ref_year) &
            (df_filtered['FECHA'].dt.month <= fecha_corte.month) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].groupby(['Suc_agrupada', 'LINEA_PLUS'], dropna=False)['PRESUPUESTO'].sum().reset_index()

    if df_pres_suc.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_pres_suc['PRESUPUESTO'] = pd.to_numeric(df_pres_suc['PRESUPUESTO'], errors='coerce').fillna(0.0)
    
    # ✅ TOTAL DE PRESUPUESTO POR LÍNEA
    pres_total_por_linea = df_pres_suc.groupby('LINEA_PLUS')['PRESUPUESTO'].sum()

    # ========== 3. CALCULAR MÉTRICA PROPORCIONAL POR SUCURSAL (vectorizado) ==========
    df_pres_suc['_presup_total'] = df_pres_suc['LINEA_PLUS'].map(pres_total_por_linea).fillna(0.0)
    df_pres_suc['_metric_total'] = df_pres_suc['LINEA_PLUS'].map(metric_total_por_linea).fillna(0.0)

    # ✅ DISTRIBUCIÓN PROPORCIONAL vectorizada
    df_pres_suc['metric_value'] = np.where(
        df_pres_suc['_presup_total'] > 0,
        df_pres_suc['_metric_total'] * df_pres_suc['PRESUPUESTO'] / df_pres_suc['_presup_total'],
        0.0
    )

    df_resultado = df_pres_suc[['Suc_agrupada', 'LINEA_PLUS', 'metric_value']].copy()
    df_pres_suc.drop(columns=['_presup_total', '_metric_total', 'metric_value'], inplace=True)
    
    if df_resultado.empty:
        return pd.DataFrame(), pd.DataFrame()

    # ========== 4. CREAR PIVOT TABLE ==========
    pivot_metric = df_resultado.pivot_table(
        index='Suc_agrupada', 
        columns='LINEA_PLUS', 
        values='metric_value', 
        aggfunc='sum', 
        fill_value=0
    )
    
    if pivot_metric.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Filtrar filas con todos ceros
    pivot_metric = pivot_metric[pivot_metric.sum(axis=1) != 0]
    
    if pivot_metric.empty:
        return pd.DataFrame(), pd.DataFrame()

    # ========== 5. ORDENAR Y CREAR TABLA EXPORTABLE ==========
    pivot_metric_detalle = pivot_metric.loc[
        pivot_metric.sum(axis=1).sort_values(ascending=False).index
    ]
    
    totales_linea = pivot_metric_detalle.sum(axis=0)
    pivot_metric_export = pd.concat(
        [pivot_metric_detalle, pd.DataFrame([totales_linea], index=['TOTAL LÍNEA'])]
    )
    
    return pivot_metric_detalle, pivot_metric_export


def _build_faltante_heatmap_data(
    df_filtered: pd.DataFrame,
    vista_mes: str,
    periodo_actual: pd.Timestamp,
    meses_quarter: list[int],
    ref_year: int,
    fecha_corte: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula faltante directo por sucursal × línea: PRESUPUESTO - IMP_PRIMA."""
    required_cols = {'FECHA', 'Suc_agrupada', 'LINEA_PLUS', 'PRESUPUESTO', 'IMP_PRIMA'}
    if not required_cols.issubset(df_filtered.columns):
        return pd.DataFrame(), pd.DataFrame()

    if vista_mes == "Mes":
        df_metric = df_filtered[
            (df_filtered['FECHA'] == periodo_actual) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].copy()
    elif vista_mes == "Año":
        df_metric = df_filtered[
            (df_filtered['FECHA'].dt.year == ref_year) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].copy()
    else:
        df_metric = df_filtered[
            (df_filtered['FECHA'].dt.year == ref_year) &
            (df_filtered['FECHA'].dt.month <= fecha_corte.month) &
            (df_filtered['FECHA'].dt.month.isin(meses_quarter))
        ].copy()

    if df_metric.empty:
        return pd.DataFrame(), pd.DataFrame()

    df_metric['PRESUPUESTO'] = pd.to_numeric(df_metric['PRESUPUESTO'], errors='coerce').fillna(0.0)
    df_metric['IMP_PRIMA'] = pd.to_numeric(df_metric['IMP_PRIMA'], errors='coerce').fillna(0.0)

    df_resultado = (
        df_metric
        .groupby(['Suc_agrupada', 'LINEA_PLUS'], dropna=False)[['PRESUPUESTO', 'IMP_PRIMA']]
        .sum()
        .reset_index()
    )
    df_resultado['metric_value'] = df_resultado['PRESUPUESTO'] - df_resultado['IMP_PRIMA']

    pivot_metric = df_resultado.pivot_table(
        index='Suc_agrupada',
        columns='LINEA_PLUS',
        values='metric_value',
        aggfunc='sum',
        fill_value=0
    )

    if pivot_metric.empty:
        return pd.DataFrame(), pd.DataFrame()

    pivot_metric = pivot_metric[pivot_metric.sum(axis=1) != 0]
    if pivot_metric.empty:
        return pd.DataFrame(), pd.DataFrame()

    pivot_metric_detalle = pivot_metric.loc[
        pivot_metric.sum(axis=1).sort_values(ascending=False).index
    ]
    totales_linea = pivot_metric_detalle.sum(axis=0)
    pivot_metric_export = pd.concat(
        [pivot_metric_detalle, pd.DataFrame([totales_linea], index=['TOTAL LÍNEA'])]
    )

    return pivot_metric_detalle, pivot_metric_export


@st.cache_data(ttl=3600, show_spinner=False)
def calculate_monthly_distribution_cached(
    df_filtered: pd.DataFrame,
    ref_year: int,
    cutoff_date: pd.Timestamp,
    meses_quarter: tuple[int, ...],
) -> tuple[pd.DataFrame, tuple[int, ...]]:
    """Cache dedicado para la distribución mensual."""
    return build_monthly_distribution(
        df_filtered=df_filtered,
        ref_year=ref_year,
        cutoff_date=cutoff_date,
        meses_quarter=meses_quarter,
    )


@st.cache_data(ttl=3600, show_spinner=False)
def build_distribution_html_cached(
    df_distribution: pd.DataFrame,
    remaining_months: tuple[int, ...],
    ref_year: int,
    cutoff_date: pd.Timestamp,
) -> str:
    """Cachea la construcción del HTML de la distribución."""
    return build_distribution_html(
        df_distribution=df_distribution,
        remaining_months=remaining_months,
        ref_year=ref_year,
        cutoff_date=cutoff_date,
    )


def _distribution_cache_key(
    quarter_sel: str,
    periodo_actual: pd.Timestamp,
    filters: dict,
) -> tuple:
    """Clave estable para session_state evitando recálculos repetidos."""
    return (
        quarter_sel,
        str(periodo_actual.date()),
        filters.get('linea_plus'),
        tuple(filters.get('codigos') or []),
        tuple(filters.get('sucursales') or []),
        tuple(filters.get('suc_agrupadas') or []),
        filters.get('anio_analisis'),
    )


def _apply_increment_pct_conditional_formatting(
    worksheet,
    df_distribution_export: pd.DataFrame,
    remaining_months: tuple[int, ...],
) -> None:
    """Aplica semáforo a columnas de incremento porcentual en Excel."""
    if df_distribution_export.empty:
        return

    red_fill = PatternFill(fill_type="solid", fgColor="FECACA")
    orange_fill = PatternFill(fill_type="solid", fgColor="FED7AA")
    green_fill = PatternFill(fill_type="solid", fgColor="DCFCE7")
    data_end_row = len(df_distribution_export) + 1

    for month in remaining_months:
        col_name = f'{MONTH_ABBR[month]}_Incremento_Pct'
        try:
            col_idx = df_distribution_export.columns.get_loc(col_name) + 1
        except KeyError:
            continue
        col_letter = get_column_letter(col_idx)
        cell_range = f"{col_letter}2:{col_letter}{data_end_row}"
        worksheet.conditional_formatting.add(
            cell_range,
            CellIsRule(operator='greaterThan', formula=[str(_INCREMENT_PCT_HIGH_THRESHOLD)], fill=red_fill),
        )
        worksheet.conditional_formatting.add(
            cell_range,
            CellIsRule(
                operator='between',
                formula=[str(_INCREMENT_PCT_MEDIUM_THRESHOLD), str(_INCREMENT_PCT_HIGH_THRESHOLD)],
                fill=orange_fill,
            ),
        )
        worksheet.conditional_formatting.add(
            cell_range,
            CellIsRule(operator='lessThan', formula=[str(_INCREMENT_PCT_MEDIUM_THRESHOLD)], fill=green_fill),
        )


@_fragment_compat
def render_deficit_heatmap_fragment(
    df_filtered: pd.DataFrame,
    df_resumen: pd.DataFrame,
    metric_col: str,
    vista_mes: str,
    periodo_actual: pd.Timestamp,
    meses_quarter: tuple[int, ...],
    ref_year: int,
    fecha_corte: pd.Timestamp,
) -> pd.DataFrame:
    """Renderiza el mapa de calor 1 dentro de un fragmento."""
    with st.expander("🔥 Mapa de Calor 1 — Déficit vs Meta por Sucursal y Línea", expanded=False):
        if 'Suc_agrupada' not in df_filtered.columns:
            st.info("No hay columna Suc_agrupada disponible para mostrar la matriz")
            return pd.DataFrame()
        if 'PRESUPUESTO' not in df_filtered.columns:
            st.info("📊 No se puede construir el mapa de calor porque no existe la columna PRESUPUESTO.")
            return pd.DataFrame()

        pivot_deficit_detalle, pivot_deficit = _build_branch_heatmap_data(
            df_filtered=df_filtered,
            df_resumen=df_resumen,
            metric_col=metric_col,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            meses_quarter=list(meses_quarter),
            ref_year=ref_year,
            fecha_corte=fecha_corte,
        )

        if pivot_deficit.empty:
            st.info("📊 No hay datos de presupuesto por sucursal para construir el mapa de calor.")
            return pd.DataFrame()

        totales_linea = pivot_deficit.loc['TOTAL LÍNEA']
        heatmap_html = _build_heatmap_html(
            pivot_deficit_detalle=pivot_deficit_detalle,
            totales_linea=totales_linea,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            title_text="🔥 Déficit vs Meta",
            legend_text="🔴 Rojo intenso = valores positivos (Déficit vs pronóstico) | ⬜ Crema = cero o faltante",
            note_text="⚠️ La métrica es Proyectado(-)Pronóstico: los valores positivos tienen una animación suave como señal de alerta visual frente al riesgo de déficit frente al pronóstico.",
        )
        st.markdown(heatmap_html, unsafe_allow_html=True)
        st.caption("🔴 Rojo escarlata = valores positivos de Proyectado(-)Pronóstico (superávit frente al pronóstico) | ⬜ Blanco crema = cero o faltante | Los totales por línea se muestran antes del detalle por sucursal")
        return pivot_deficit


@_fragment_compat
def render_faltante_heatmap_fragment(
    df_filtered: pd.DataFrame,
    vista_mes: str,
    periodo_actual: pd.Timestamp,
    meses_quarter: tuple[int, ...],
    ref_year: int,
    fecha_corte: pd.Timestamp,
) -> pd.DataFrame:
    """Renderiza el mapa de calor 2 dentro de un fragmento."""
    with st.expander("🔥 Mapa de Calor 2 — Faltante Proyectado por Sucursal y Línea", expanded=False):
        if 'Suc_agrupada' not in df_filtered.columns:
            st.info("No hay columna Suc_agrupada disponible para mostrar la matriz")
            return pd.DataFrame()
        if 'PRESUPUESTO' not in df_filtered.columns:
            st.info("📊 No se puede construir el mapa de calor porque no existe la columna PRESUPUESTO.")
            return pd.DataFrame()

        pivot_faltante_detalle, pivot_faltante = _build_faltante_heatmap_data(
            df_filtered=df_filtered,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            meses_quarter=list(meses_quarter),
            ref_year=ref_year,
            fecha_corte=fecha_corte,
        )

        if pivot_faltante.empty:
            st.info("📊 No hay datos de presupuesto por sucursal para construir el mapa de calor.")
            return pd.DataFrame()

        totales_linea = pivot_faltante.loc['TOTAL LÍNEA']
        heatmap_html = _build_heatmap_html(
            pivot_deficit_detalle=pivot_faltante_detalle,
            totales_linea=totales_linea,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            title_text="🔥 Faltante Proyectado",
            legend_text="🔴 Rojo = falta producir | 🟢 Verde = meta cumplida | ⬜ Crema = cero",
            note_text="⚠️ El Faltante Proyectado muestra lo que resta por producir vs. presupuesto basado en producción REAL actual (no incluye pronóstico). Valores positivos indican que falta cumplir meta.",
            highlight_negative=True,
        )
        st.markdown(heatmap_html, unsafe_allow_html=True)
        st.caption("🔴 Rojo = falta producir | 🟢 Verde = meta cumplida | ⬜ Crema = cero | Los totales por línea se muestran antes del detalle por sucursal")
        return pivot_faltante


@_fragment_compat
def render_monthly_distribution_fragment(
    df_filtered: pd.DataFrame,
    quarter_sel: str,
    fecha_corte: pd.Timestamp,
    ref_year: int,
    meses_quarter: tuple[int, ...],
    filters: dict,
) -> tuple[pd.DataFrame, tuple[int, ...]]:
    """Renderiza la nueva matriz mensual usando caché de session_state."""
    with st.expander("📅 Matriz desplegable — Distribución mensual del faltante proyectado", expanded=False):
        if 'Suc_agrupada' not in df_filtered.columns:
            st.info("No hay columna Suc_agrupada disponible para mostrar la distribución mensual.")
            return pd.DataFrame(), tuple()
        if 'PRESUPUESTO' not in df_filtered.columns:
            st.info("📊 No se puede construir la distribución porque no existe la columna PRESUPUESTO.")
            return pd.DataFrame(), tuple()

        periodo_referencia = pd.Timestamp(year=fecha_corte.year, month=fecha_corte.month, day=1)
        cache_key = _distribution_cache_key(quarter_sel, periodo_referencia, filters)
        cache_store = st.session_state.setdefault('distribucion_cache', {})
        cache_hit = cache_key in cache_store

        if cache_hit:
            df_distribution, remaining_months = cache_store[cache_key]
            st.caption("⚡ Datos cargados desde caché de sesión")
        else:
            with st.spinner("🔄 Calculando faltante proyectado acumulado y distribuyéndolo..."):
                df_distribution, remaining_months = calculate_monthly_distribution_cached(
                    df_filtered=df_filtered,
                    ref_year=ref_year,
                    cutoff_date=fecha_corte,
                    meses_quarter=meses_quarter,
                )
            if len(cache_store) >= _MAX_DISTRIBUTION_CACHE_SIZE:
                first_key = next(iter(cache_store))
                cache_store.pop(first_key, None)
            cache_store[cache_key] = (df_distribution, remaining_months)

        if df_distribution.empty or not remaining_months:
            st.info("📊 No hay presupuesto restante disponible para distribuir el faltante proyectado con los filtros actuales.")
            return pd.DataFrame(), tuple()

        with st.spinner("📊 Generando tabla interactiva..."):
            html_table = build_distribution_html_cached(
                df_distribution=df_distribution,
                remaining_months=remaining_months,
                ref_year=ref_year,
                cutoff_date=fecha_corte,
            )
        component_height = min(max(520, 280 + (len(df_distribution) + 1) * 34), 1100)
        components.html(html_table, height=component_height, scrolling=True)
        st.caption(
            "✅ Validación: Presupuesto Total Año = producción real acumulada hasta el mes anterior "
            "+ nuevos objetivos distribuidos en los meses mostrados."
        )
        return df_distribution, remaining_months


@st.cache_resource
def _img_to_b64(path: str) -> str:
    """Carga una imagen local y la retorna como string base64 para embeber en HTML/CSS."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except FileNotFoundError:
        import warnings as _warnings
        _warnings.warn(f"Imagen no encontrada: {path}. Se usará el fallback visual CSS.", stacklevel=2)
        return ""


# ====================  PAGE CONFIG ====================
st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon=PAGE_ICON,
    layout=LAYOUT
)

st.markdown("""
<style>:root{--bg:#f8fafc;--fg:#1e293b;--accent:#0284c7;--muted:#64748b;--card:#ffffff;--border:#e2e8f0;--up:#16a34a;--down:#ef4444;--near:#f59e0b;}body,.stApp{background:var(--bg);color:var(--fg);}.block-container{padding-top:.6rem;}.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:12px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);}.table-wrap{overflow:auto;border:1px solid var(--border);border-radius:12px;background:var(--card);padding:6px;}.tbl{width:100%;border-collapse:collapse;font-size:14px;color:var(--fg);}.tbl thead th{position:sticky;top:0;background:#f1f5f9;color:#334155;padding:10px;border-bottom:2px solid var(--border);text-align:left;}.tbl td{padding:8px;border-bottom:1px dashed var(--border);white-space:nowrap;color:var(--fg);}.bad{color:var(--down);font-weight:700;}.ok{color:var(--up);font-weight:700;}.near{color:var(--near);font-weight:700;}.muted{color:var(--muted);}.small{font-size:12px;color:var(--muted);}.heatmap-shell{border:1px solid var(--border);border-radius:18px;overflow:hidden;background:linear-gradient(180deg,#fff,#f8fafc);box-shadow:0 4px 14px rgba(15,23,42,0.08);}.heatmap-banner{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 18px;background:linear-gradient(90deg,rgba(2,132,199,0.10),rgba(248,250,252,0.95) 65%,rgba(245,158,11,0.08));border-bottom:1px solid var(--border);}.heatmap-title{font-size:15px;font-weight:700;color:#0f172a;}.heatmap-legend{font-size:12px;color:#475569;text-align:right;}.heatmap-grid{display:grid;align-items:stretch;}.heatmap-total-label,.heatmap-total-cell,.heatmap-corner-label,.heatmap-col-head,.heatmap-row-label,.heatmap-cell{position:relative;display:flex;align-items:center;justify-content:center;min-height:64px;padding:10px 12px;text-align:center;border-right:1px solid var(--border);border-bottom:1px solid var(--border);}.heatmap-total-label,.heatmap-corner-label,.heatmap-row-label{justify-content:flex-start;}.heatmap-total-label{font-weight:800;color:#0f172a;background:linear-gradient(135deg,rgba(2,132,199,0.12),rgba(148,163,184,0.10));}.heatmap-total-cell{flex-direction:column;gap:4px;}.heatmap-total-caption{font-size:11px;letter-spacing:.08em;text-transform:uppercase;opacity:.75;color:#475569;}.heatmap-total-value{font-size:17px;font-weight:800;line-height:1.1;}.heatmap-corner-label{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#475569;background:#f8fafc;}.heatmap-col-head{min-height:56px;background:#f1f5f9;color:#0f172a;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;}.heatmap-row-label{font-size:13px;font-weight:600;color:#0f172a;background:#f8fafc;}.heatmap-cell{font-size:13px;font-weight:700;}.heatmap-cell-positive,.heatmap-total-positive{z-index:0;}.heatmap-cell-positive::after,.heatmap-total-positive::after{content:"";position:absolute;inset:8px;border-radius:12px;border:1px solid rgba(239,68,68,0.34);animation:heatPulse 1.35s ease-in-out infinite;pointer-events:none;}.heatmap-note{padding:12px 16px;font-size:12px;color:#475569;background:rgba(241,245,249,0.85);}.stTabs [data-baseweb="tab-list"]{gap:4px;background:transparent;}.stTabs [data-baseweb="tab"]{color:#cbd5e1 !important;font-weight:600 !important;font-size:14px !important;padding:8px 20px !important;border-radius:8px 8px 0 0 !important;background:rgba(30,41,59,0.6) !important;border:1px solid rgba(255,255,255,0.08) !important;border-bottom:none !important;transition:all 0.2s ease !important;}.stTabs [data-baseweb="tab"]:hover{color:#f1f5f9 !important;background:rgba(51,65,85,0.8) !important;}.stTabs [aria-selected="true"]{color:#ffffff !important;background:rgba(2,132,199,0.25) !important;border-color:rgba(56,189,248,0.4) !important;border-bottom:2px solid #38bdf8 !important;}.stTabs [data-baseweb="tab"] p,.stTabs [data-baseweb="tab"] span,.stTabs [data-baseweb="tab"] div{color:inherit !important;font-size:inherit !important;font-weight:inherit !important;}@keyframes heatPulse{0%,100%{transform:scale(1);opacity:.22;box-shadow:0 0 0 0 rgba(239,68,68,0);}45%{transform:scale(1.03);opacity:.58;box-shadow:0 0 0 8px rgba(239,68,68,0.10);}75%{transform:scale(1.01);opacity:.34;box-shadow:0 0 0 3px rgba(239,68,68,0.16);}}@media (prefers-reduced-motion: reduce){.heatmap-cell-positive::after,.heatmap-total-positive::after{animation:none;opacity:.35;box-shadow:0 0 0 2px rgba(239,68,68,0.12);}}</style>
""", unsafe_allow_html=True)

# ==================== LOAD BRAND IMAGES ====================
_BANNER_SDE_B64 = _img_to_b64("SDE_Primera_Pag.png")
_LOGO_70_B64 = _img_to_b64("logo_70_anios.png")
@st.cache_data(ttl=3600, show_spinner=False, max_entries=_DATA_CACHE_MAX_ENTRIES)
def load_and_process_data():
    """Carga y procesa datos con caché para reducir recargas y mejorar rendimiento."""
    df_raw = load_data()
    df_processed = normalize_dataframe(df_raw)
    fecha_corte = load_cutoff_date()
    return df_processed, fecha_corte


@st.cache_data(ttl=3600)
def nowcast_cached(prod_parcial: float, fecha_corte: pd.Timestamp,
                   pronostico_completo: float) -> float:
    """Calcula nowcast en caché - se actualiza cada hora (TTL 3600s).

    Fórmula: prod_parcial + pronostico_completo × (días_restantes / días_totales)
    """
    from utils.date_utils import business_days_left, get_month_range
    primer_dia, ultimo_dia = get_month_range(fecha_corte.year, fecha_corte.month)
    dias_totales = business_days_left(primer_dia, ultimo_dia)
    dias_restantes = business_days_left(fecha_corte, ultimo_dia)
    if dias_totales <= 0:
        return prod_parcial
    proporcion_restante = dias_restantes / dias_totales
    return prod_parcial + pronostico_completo * proporcion_restante

@st.cache_data(ttl=3600)
def compute_line_forecast(serie_data: tuple, conservative_factor: float,
                          ref_year: int, fecha_corte_str: str,
                          steps: int = 1) -> dict:
    """Calcula pronóstico para una línea específica (cacheado).

    Args:
        serie_data: tuple de (fechas_iso, valores) para permitir hash
        conservative_factor: factor de ajuste conservador
        ref_year: año de referencia
        fecha_corte_str: fecha de corte como string ISO para hash
        steps: número de pasos a pronosticar

    Returns:
        dict con las claves:
            fc_fechas (list[str]): fechas ISO del pronóstico
            fc_valores (list[float]): valores de Pronostico_mensual
            fc_ic_hi (list[float]): límite superior IC 95% (vacío si no disponible)
            fc_ic_lo (list[float]): límite inferior IC 95% (vacío si no disponible)
            is_partial (bool): True si el mes actual es parcial
            cur_month_str (str | None): mes actual como string ISO, o None
    """
    fechas, valores = serie_data
    serie = pd.Series(list(valores), index=pd.to_datetime(list(fechas)))
    engine = ForecastEngine(conservative_factor=conservative_factor)
    fecha_corte_ts = pd.Timestamp(fecha_corte_str)
    serie_clean = engine.sanitize_series(serie, ref_year)
    serie_train, cur_month, is_partial = engine.split_series_exclude_partial(
        serie_clean, ref_year, fecha_corte_ts
    )
    _, fc_df, _, _ = engine.fit_forecast(serie_train, steps=steps)
    if fc_df.empty:
        return {'fc_fechas': [], 'fc_valores': [], 'fc_ic_hi': [], 'fc_ic_lo': [],
                'is_partial': is_partial, 'cur_month_str': None}
    return {
        'fc_fechas': [str(d) for d in fc_df['FECHA']],
        'fc_valores': list(fc_df['Pronostico_mensual']),
        'fc_ic_hi': list(fc_df['IC_hi']) if 'IC_hi' in fc_df.columns else [],
        'fc_ic_lo': list(fc_df['IC_lo']) if 'IC_lo' in fc_df.columns else [],
        'is_partial': is_partial,
        'cur_month_str': str(cur_month) if cur_month is not None else None,
    }


def serialize_series_for_cache(serie: pd.Series) -> tuple:
    """Convierte una serie temporal en un tuple hashable para cache."""
    return (
        tuple(str(d) for d in serie.index),
        tuple(float(v) for v in serie.values),
    )


def fmt_cop_short(value: float) -> str:
    """Formato corto para etiquetas de gráficos (ej: $2.3M, $450.8K, $980)."""
    value = float(value)
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if abs_value >= 1_000_000:
        return f"{sign}${abs_value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{sign}${abs_value / 1_000:.1f}K"
    return f"{sign}{fmt_cop(abs_value)}"


def _line_adjustment_factor(linea: str) -> float:
    """Retorna el factor de ajuste conservador por línea de negocio.

    Ajustes conservadores:
    - FIANZAS: 0.97 (-3.0%)
    - SOAT: 1.0 (0%)
    - Otras líneas: 0.995 (-0.5%)
    """
    if linea == "FIANZAS":
        return 0.97
    if linea == "SOAT":
        return 1.0
    return 0.995


def _compute_single_line_detailed_forecast(
    df_linea: pd.DataFrame,
    linea: str,
    conservative_factor: float,
    ref_year: int,
    fecha_corte: pd.Timestamp,
) -> pd.DataFrame:
    if df_linea.empty:
        return pd.DataFrame()

    serie_linea = df_linea.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
    if serie_linea.empty:
        return pd.DataFrame()

    engine_temp = ForecastEngine(conservative_factor=conservative_factor)
    serie_clean_temp = engine_temp.sanitize_series(serie_linea, ref_year)
    serie_train_temp, cur_month_temp, is_partial_temp = engine_temp.split_series_exclude_partial(
        serie_clean_temp, ref_year, fecha_corte
    )

    if not is_partial_temp and fecha_corte.month == 12:
        return pd.DataFrame()

    if is_partial_temp and cur_month_temp:
        last_month_temp = max(0, cur_month_temp.month - 1)
    else:
        last_month_temp = (
            serie_train_temp.index.max().month if not serie_train_temp.empty else fecha_corte.month
        )

    steps_temp = max(0, 12 - last_month_temp)
    if steps_temp <= 0:
        return pd.DataFrame()

    fc_result = compute_line_forecast(
        serialize_series_for_cache(serie_linea),
        conservative_factor,
        ref_year,
        str(fecha_corte.date()),
        steps=steps_temp,
    )

    if not fc_result['fc_fechas']:
        return pd.DataFrame()

    forecast_df = pd.DataFrame({
        'FECHA': pd.to_datetime(fc_result['fc_fechas']),
        'Pronostico_mensual': fc_result['fc_valores'],
        'IC_lo': fc_result['fc_ic_lo'] if fc_result['fc_ic_lo'] else fc_result['fc_valores'],
        'IC_hi': fc_result['fc_ic_hi'] if fc_result['fc_ic_hi'] else fc_result['fc_valores'],
    })
    forecast_df = forecast_df[forecast_df['FECHA'].dt.year == ref_year].copy()
    if forecast_df.empty:
        return forecast_df

    factor = _line_adjustment_factor(linea)
    forecast_df[['Pronostico_mensual', 'IC_lo', 'IC_hi']] = (
        forecast_df[['Pronostico_mensual', 'IC_lo', 'IC_hi']] * factor
    )

    current_month = pd.Timestamp(year=fecha_corte.year, month=fecha_corte.month, day=1)
    if (
        fc_result.get('is_partial')
        and not forecast_df.empty
        and forecast_df.iloc[0]['FECHA'] == current_month
    ):
        prod_mes_actual = df_linea[df_linea['FECHA'] == current_month]['IMP_PRIMA'].sum()
        forecast_full = float(forecast_df.iloc[0]['Pronostico_mensual'])
        nowcast_value = nowcast_cached(prod_mes_actual, fecha_corte, forecast_full)
        delta = nowcast_value - forecast_full
        forecast_df.loc[forecast_df.index[0], 'Pronostico_mensual'] = nowcast_value
        forecast_df.loc[forecast_df.index[0], 'IC_lo'] = max(
            0.0, float(forecast_df.loc[forecast_df.index[0], 'IC_lo']) + delta
        )
        forecast_df.loc[forecast_df.index[0], 'IC_hi'] = max(
            float(forecast_df.loc[forecast_df.index[0], 'IC_lo']),
            float(forecast_df.loc[forecast_df.index[0], 'IC_hi']) + delta,
        )

    forecast_df[['Pronostico_mensual', 'IC_lo', 'IC_hi']] = (
        forecast_df[['Pronostico_mensual', 'IC_lo', 'IC_hi']].clip(lower=0.0)
    )
    forecast_df['IC_hi'] = forecast_df[['IC_lo', 'IC_hi']].max(axis=1)
    return forecast_df.sort_values('FECHA')


def _serialize_dataframe_for_cache(df: pd.DataFrame) -> tuple:
    """Convierte DataFrame en tuple hasheable para st.cache_data.

    Retorna una tupla (records_list, columns_list) para reconstruir el DataFrame.
    """
    if df.empty:
        return ([], [])
    return (df.to_dict('records'), list(df.columns))


@st.cache_data(ttl=_DETAILED_FORECAST_CACHE_TTL_SECONDS, show_spinner=False)
def build_detailed_forecast(
    df_scope_hash: tuple,
    linea_seleccionada: str,
    conservative_factor: float,
    ref_year: int,
    fecha_corte_str: str,
) -> pd.DataFrame:
    df_scope = pd.DataFrame(df_scope_hash[0], columns=df_scope_hash[1])
    # Al reconstruir desde records, FECHA puede regresar como string/objeto.
    if 'FECHA' in df_scope.columns and not pd.api.types.is_datetime64_any_dtype(df_scope['FECHA']):
        df_scope['FECHA'] = pd.to_datetime(df_scope['FECHA'], errors='coerce')
    fecha_corte = pd.Timestamp(fecha_corte_str)

    if df_scope.empty or 'LINEA_PLUS' not in df_scope.columns:
        return pd.DataFrame()

    if linea_seleccionada == "TODAS":
        forecast_frames = []
        lineas_scope = sorted(df_scope['LINEA_PLUS'].dropna().unique())
        for linea in lineas_scope:
            df_linea = df_scope[df_scope['LINEA_PLUS'] == linea]
            fc_linea = _compute_single_line_detailed_forecast(
                df_linea, linea, conservative_factor, ref_year, fecha_corte
            )
            if not fc_linea.empty:
                forecast_frames.append(fc_linea)

        if not forecast_frames:
            return pd.DataFrame()

        forecast_df = pd.concat(forecast_frames, ignore_index=True)
        forecast_df = (
            forecast_df.groupby('FECHA', as_index=False)[['Pronostico_mensual', 'IC_lo', 'IC_hi']].sum()
        )
    else:
        df_linea = df_scope[df_scope['LINEA_PLUS'] == linea_seleccionada]
        forecast_df = _compute_single_line_detailed_forecast(
            df_linea, linea_seleccionada, conservative_factor, ref_year, fecha_corte
        )

    if forecast_df.empty:
        return forecast_df

    forecast_df = forecast_df.sort_values('FECHA').copy()
    forecast_df['Pronostico_acumulado'] = forecast_df['Pronostico_mensual'].cumsum()
    forecast_df['IC_acum_lo'] = forecast_df['IC_lo'].cumsum()
    forecast_df['IC_acum_hi'] = forecast_df['IC_hi'].cumsum()
    return forecast_df


def should_show_ley_garantias(df_scope: pd.DataFrame, linea_seleccionada: str) -> bool:
    if linea_seleccionada == "FIANZAS":
        return True
    if linea_seleccionada != "TODAS" or 'LINEA_PLUS' not in df_scope.columns:
        return False
    return "FIANZAS" in set(df_scope['LINEA_PLUS'].dropna().unique())


def get_ley_garantias_end_date() -> pd.Timestamp:
    ley_garantias_key = (
        'fin_segunda_vuelta'
        if LEY_GARANTIAS_2026.get('usar_segunda_vuelta', False)
        else 'fin_primera_vuelta'
    )
    ley_end_raw = LEY_GARANTIAS_2026.get(ley_garantias_key)
    if not ley_end_raw:
        return pd.NaT
    try:
        return pd.Timestamp(ley_end_raw)
    except Exception:
        return pd.NaT


def render_detailed_forecast_charts(
    forecast_df: pd.DataFrame,
    chart_label: str,
    ref_year: int,
    show_ley: bool,
) -> None:
    if forecast_df.empty:
        st.warning("No hay datos suficientes para generar el pronóstico detallado")
        return

    fig_monthly = go.Figure()
    fig_monthly.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['IC_hi'],
        mode='lines',
        line=dict(color='#16a34a', width=2),
        name='IC 95% Superior',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))
    fig_monthly.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['IC_lo'],
        mode='lines',
        line=dict(color='#ef4444', width=2),
        fill='tonexty',
        fillcolor='rgba(56,189,248,0.2)',
        name='IC 95% Inferior',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))
    fig_monthly.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['Pronostico_mensual'],
        mode='lines+markers+text',
        line=dict(color='#38bdf8', width=3),
        marker=dict(size=8, symbol='circle'),
        text=forecast_df['Pronostico_mensual'].apply(fmt_cop_short),
        textposition='top center',
        name='Pronóstico',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))

    fig_accum = go.Figure()
    fig_accum.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['IC_acum_hi'],
        mode='lines',
        line=dict(color='#16a34a', width=2),
        name='IC 95% Acumulado Superior',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))
    fig_accum.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['IC_acum_lo'],
        mode='lines',
        line=dict(color='#ef4444', width=2),
        fill='tonexty',
        fillcolor='rgba(56,189,248,0.2)',
        name='IC 95% Acumulado Inferior',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))
    fig_accum.add_trace(go.Scatter(
        x=forecast_df['FECHA'],
        y=forecast_df['Pronostico_acumulado'],
        mode='lines+markers+text',
        line=dict(color='#38bdf8', width=3),
        marker=dict(size=8, symbol='circle'),
        text=forecast_df['Pronostico_acumulado'].apply(fmt_cop_short),
        textposition='top center',
        name='Pronóstico Acumulado',
        hovertemplate='$%{y:,.0f}<extra></extra>',
    ))

    if show_ley:
        ley_end = get_ley_garantias_end_date()
        if pd.notna(ley_end):
            ley_end_str = ley_end.strftime('%Y-%m-%d')
            for fig in [fig_monthly, fig_accum]:
                fig.add_vline(
                    x=ley_end_str,
                    line_dash='dot',
                    line_color='#f59e0b',
                    line_width=2,
                    annotation_text='Fin Ley de Garantías',
                    annotation_position='top left',
                )

    common_layout = dict(
        template='plotly_dark',
        height=_DETAILED_CHART_HEIGHT,
        margin=dict(l=60, r=60, t=60, b=60),
        showlegend=True,
        legend=dict(x=1, y=1, xanchor='right', yanchor='top'),
        xaxis_title='Mes',
        yaxis_title='COP',
    )

    fig_monthly.update_layout(
        title=f"Pronóstico Mensual - {chart_label} {ref_year}",
        **common_layout,
    )
    fig_accum.update_layout(
        title=f"Pronóstico Acumulado - {chart_label} {ref_year}",
        **common_layout,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(fig_monthly, width='stretch')
    with col2:
        st.plotly_chart(fig_accum, width='stretch')


def render_detailed_forecast_table(forecast_df: pd.DataFrame) -> None:
    if forecast_df.empty:
        return

    summary_df = pd.DataFrame({
        'Mes': forecast_df['FECHA'].dt.strftime('%b-%Y'),
        'Pronóstico Mensual': forecast_df['Pronostico_mensual'],
        'IC Mín': forecast_df['IC_lo'],
        'IC Máx': forecast_df['IC_hi'],
        'Pronóstico Acumulado': forecast_df['Pronostico_acumulado'],
        'IC Acum Mín': forecast_df['IC_acum_lo'],
        'IC Acum Máx': forecast_df['IC_acum_hi'],
    })
    if summary_df.empty:
        return

    total_row = {
        'Mes': 'TOTAL',
        'Pronóstico Mensual': summary_df['Pronóstico Mensual'].sum(),
        'IC Mín': summary_df['IC Mín'].sum(),
        'IC Máx': summary_df['IC Máx'].sum(),
        'Pronóstico Acumulado': summary_df['Pronóstico Acumulado'].iloc[-1],
        'IC Acum Mín': summary_df['IC Acum Mín'].iloc[-1],
        'IC Acum Máx': summary_df['IC Acum Máx'].iloc[-1],
    }
    summary_df = pd.concat([summary_df, pd.DataFrame([total_row])], ignore_index=True)

    display_df = summary_df.copy()
    for col in [
        'Pronóstico Mensual', 'IC Mín', 'IC Máx',
        'Pronóstico Acumulado', 'IC Acum Mín', 'IC Acum Máx',
    ]:
        display_df[col] = display_df[col].apply(fmt_cop)

    st.dataframe(display_df, width='stretch', hide_index=True)


# ==================== VISIT COUNTER ====================
if "visit_count" not in st.session_state:
    st.session_state["visit_count"] = 0
if "visit_counted" not in st.session_state:
    st.session_state["visit_counted"] = False
if not st.session_state["visit_counted"]:
    st.session_state["visit_count"] += 1
    st.session_state["visit_counted"] = True

df, fecha_corte = load_and_process_data()

# ==================== HEADER ====================
_logo_70_tag = (
    f'<img src="data:image/png;base64,{_LOGO_70_B64}" '
    f'style="height:54px;object-fit:contain;border-radius:6px;" alt="70 años Seguros del Estado"/>'
    if _LOGO_70_B64 else
    '<div style="font-size:22px;font-weight:900;color:#d4a017;">70<br><span style=\'font-size:9px;letter-spacing:1px;\'>AÑOS</span></div>'
)

st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:6px;
     background:linear-gradient(90deg,#071428 0%,#0d1e3d 80%,#0a1628 100%);
     border-radius:10px;padding:10px 24px;box-shadow:0 2px 10px rgba(0,0,0,0.3);">
  <div style="display:flex;align-items:center;gap:14px;">
    <div style="font-size:24px;font-weight:800;color:#f3f4f6">{PAGE_ICON} {PAGE_TITLE}</div>
    <div style="opacity:.85;color:#94b8e0;font-size:13px;">Corte: {fecha_corte.strftime('%d/%m/%Y')}</div>
  </div>
  <div style="display:flex;align-items:center;gap:12px;">
    {_logo_70_tag}
  </div>
</div>
""", unsafe_allow_html=True)
st.caption("Nowcast, cierre estimado del año, ejecución vs presupuesto")

# ==================== SIDEBAR ====================
filters = render_sidebar(df, fecha_corte)

if 'distribucion_cache' not in st.session_state:
    st.session_state.distribucion_cache = {}

# ==================== APPLY FILTERS ====================
df_filtered = df.copy()

if filters['linea_plus'] != "TODAS" and 'LINEA_PLUS' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['LINEA_PLUS'] == filters['linea_plus']]

# Filtrar por Código (si columna existe y hay selección)
if filters.get('codigos') and 'CODIGO' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['CODIGO'].isin(filters['codigos'])]

# Filtrar por Sucursal (si columna existe y hay selección)
if filters.get('sucursales') and 'SUCURSAL' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['SUCURSAL'].isin(filters['sucursales'])]

# Filtrar por Sucursal Agrupada (si columna existe y hay selección)
if filters.get('suc_agrupadas') and 'Suc_agrupada' in df_filtered.columns:
    df_filtered = df_filtered[df_filtered['Suc_agrupada'].isin(filters['suc_agrupadas'])]

# Filtrar por año de análisis
df_filtered = df_filtered[df_filtered['FECHA'].dt.year <= filters['anio_analisis']]

# ==================== TABS ====================
tabs = st.tabs(["🏠 Presentación", "📈 Primas", "🏛️ FIANZAS"])

# ========== TAB 1: PRESENTACIÓN ==========
with tabs[0]:
    st.markdown("""
    <style>
    .hero-section {
        position: relative;
        width: 100%;
        min-height: 480px;
        border-radius: 14px;
        overflow: hidden;
        margin-bottom: 24px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        background: #071428;
    }
    .hero-bg {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        object-position: center center;
        z-index: 0;
    }
    .hero-overlay {
        position: absolute;
        inset: 0;
        background: linear-gradient(
            to bottom,
            rgba(7,20,40,0.10) 0%,
            rgba(7,20,40,0.35) 45%,
            rgba(7,20,40,0.88) 80%,
            rgba(7,20,40,0.96) 100%
        );
        z-index: 1;
    }
    .hero-content {
        position: relative;
        z-index: 2;
        padding: 36px 44px 40px 44px;
    }
    .hero-tagline {
        font-size: 13px;
        color: #c8ddf7;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 8px;
        font-weight: 500;
    }
    .hero-title {
        font-size: 40px;
        font-weight: 900;
        color: #f3f4f6;
        line-height: 1.1;
        margin-bottom: 6px;
    }
    .hero-title span { color: #d4a017; }
    .hero-subtitle {
        font-size: 15px;
        color: #c8ddf7;
        margin-bottom: 22px;
        font-style: italic;
    }
    .hero-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 8px;
    }
    .hero-pill {
        background: rgba(255,255,255,0.10);
        border: 1px solid rgba(212,160,23,0.35);
        border-radius: 20px;
        padding: 6px 16px;
        font-size: 13px;
        color: #e2eaf7;
        font-weight: 500;
    }
    .visit-badge {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        background: rgba(212,160,23,0.18);
        border: 1px solid rgba(212,160,23,0.55);
        border-radius: 20px;
        padding: 5px 16px;
        font-size: 13px;
        color: #d4a017;
        font-weight: 700;
        margin-top: 16px;
    }
    </style>
    """, unsafe_allow_html=True)

    visit_count = st.session_state.get("visit_count", 1)

    _bg_img_tag = (
        f'<img class="hero-bg" src="data:image/png;base64,{_BANNER_SDE_B64}" alt=""/>'
        if _BANNER_SDE_B64 else ""
    )
    _bg_fallback_style = (
        "" if _BANNER_SDE_B64
        else 'style="background:linear-gradient(135deg,#0a1628 0%,#0d2044 40%,#0f2e5a 70%,#1a3a6b 100%);"'
    )

    st.markdown(f"""
    <div class="hero-section" {_bg_fallback_style}>
        {_bg_img_tag}
        <div class="hero-overlay"></div>
        <div class="hero-content">
            <div class="hero-tagline">Modelo especializado de pronostico comercial · Seguros del Estado</div>
            <div class="hero-title">Bienvenido a <span>AseguraView</span></div>
            <div class="hero-subtitle">70 años en los que tus decisiones han hecho posible la tranquilidad de muchos</div>
            <div class="hero-pills">
                <span class="hero-pill">📈 Primas: Nowcast del mes actual y proyección de cierre anual</span>
                <span class="hero-pill">🏛️ FIANZAS: Análisis especial de la línea</span>
            </div>
            <div class="hero-pills">
                <span class="hero-pill">✅ Modelos SARIMAX/ARIMA para pronósticos</span>
                <span class="hero-pill">✅ Análisis por Línea+</span>
                <span class="hero-pill">✅ Vistas: Mes, Año, Acumulado</span>
                <span class="hero-pill">✅ Nowcast actualizado cada hora</span>
            </div>
            <div class="visit-badge">👁️ Visitas en esta sesión: {visit_count}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ========== TAB 2: PRIMAS ==========
with tabs[1]:
    st.subheader("📈 Análisis de Primas")
    
    if df_filtered.empty:
        st.warning("No hay datos con los filtros seleccionados")
        st.stop()
    
    # ==================== VISTA DEL RESUMEN ====================
    st.markdown("### Vista del Resumen")

    # Radio buttons para seleccionar vista y selector de Quarter
    col_vista, col_quarter = st.columns([2, 2])
    with col_vista:
        vista_mes = st.radio(
            "Selecciona vista del resumen",
            ["Mes", "Año", "Acumulado Mes"],
            horizontal=True,
            index=0,
            key="vista_tipo",
            label_visibility="collapsed",
        )
    with col_quarter:
        QUARTER_MONTHS = {
            "Todos": list(range(1, 13)),
            "Q1 (Ene-Mar)": [1, 2, 3],
            "Q2 (Abr-Jun)": [4, 5, 6],
            "Q3 (Jul-Sep)": [7, 8, 9],
            "Q4 (Oct-Dic)": [10, 11, 12],
        }
        quarter_sel = st.selectbox(
            "Trimestre",
            options=list(QUARTER_MONTHS.keys()),
            index=0,
            help="Filtra el resumen por trimestre",
            key="quarter_sel"
        )
    meses_quarter = QUARTER_MONTHS[quarter_sel]
    
    # ==================== CÁLCULOS POR LÍNEA+ ====================
    
    if 'LINEA_PLUS' not in df.columns:
        st.error("No existe columna LINEA_PLUS en los datos")
        st.stop()
    
    # Obtener todas las líneas disponibles
    lineas_disponibles = sorted(df['LINEA_PLUS'].dropna().unique())
    
    # Periodo actual (mes de la fecha de corte)
    periodo_actual = pd.Timestamp(year=fecha_corte.year, month=fecha_corte.month, day=1)
    
    # Filtrar datos hasta el periodo actual (usar df_filtered para respetar filtros de Sucursal/Código)
    df_periodo = df_filtered[df_filtered['FECHA'] <= periodo_actual].copy()
    
    # Generar pronóstico consolidado
    serie_prima = df_filtered.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
    engine = ForecastEngine(conservative_factor=filters['conservative_factor'])
    ref_year = filters['anio_analisis']
    serie_clean = engine.sanitize_series(serie_prima, ref_year)
    serie_train, cur_month, is_partial = engine.split_series_exclude_partial(
        serie_clean, ref_year, fecha_corte
    )
    
    if is_partial and cur_month:
        last_month = cur_month.month - 1
    else:
        last_month = serie_train.index.max().month if not serie_train.empty else fecha_corte.month - 1
    
    steps = max(1, 12 - last_month)
    
    with st.spinner("Generando pronóstico..."):
        hist_df, fc_df, smape, accuracy_df = engine.fit_forecast(serie_train, steps=steps)
    
    # Crear tabla de resumen
    resumen_lineas = []
    if vista_mes == "Año":
        previo_col = f"Previo {ref_year - 1} Año"
        actual_col = f"Actual {ref_year} Año"
    elif vista_mes == "Mes":
        previo_col = f"Previo {ref_year - 1} Mes"
        actual_col = f"Actual {ref_year} Mes"
    else:
        previo_col = f"Previo {ref_year - 1} Acumulado Mes"
        actual_col = f"Actual {ref_year} Acumulado Mes"

    faltante_col = "Faltante proyectado"
    proyectado_vs_pronostico_col = "Proyectado(-)Pronóstico"
    compensacion_col = "Compensación de faltante"
    req_dia_fc_col = "Req x día Fc (días calendario)"
    req_dia_pres_col = "Req x día Pres (días calendario)"
    
    for linea in lineas_disponibles:
        df_linea = df_periodo[df_periodo['LINEA_PLUS'] == linea]
        
        if df_linea.empty:
            continue
        
        # ========== VISTA: MES ==========
        if vista_mes == "Mes":
            # Aplicar filtro de Quarter: solo incluir si el mes actual está en el Q seleccionado
            if fecha_corte.month not in meses_quarter:
                continue

            mes_mismo_anio_previo = pd.Timestamp(year=ref_year - 1, month=fecha_corte.month, day=1)
            prod_mes_previo = df_linea[df_linea['FECHA'] == mes_mismo_anio_previo]['IMP_PRIMA'].sum()
            prod_mes_actual = df_linea[df_linea['FECHA'] == periodo_actual]['IMP_PRIMA'].sum()
            presup_mes = df_linea[df_linea['FECHA'] == periodo_actual]['PRESUPUESTO'].sum() if 'PRESUPUESTO' in df_linea.columns else 0.0

            serie_linea = df_linea.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
            fc_result = compute_line_forecast(
                serialize_series_for_cache(serie_linea),
                filters['conservative_factor'],
                fecha_corte.year,
                str(fecha_corte.date()),
                steps=1
            )
            pronostico_mes_full = fc_result['fc_valores'][0] if fc_result['fc_valores'] else 0.0
            is_partial_temp = fc_result['is_partial']

            pronostico_mes_full = pronostico_mes_full * _line_adjustment_factor(linea)

            # Nowcast: ajuste dinámico usando producción parcial + proporción restante del pronóstico
            if is_partial_temp:
                pronostico_mes = nowcast_cached(prod_mes_actual, fecha_corte, pronostico_mes_full)
            else:
                pronostico_mes = pronostico_mes_full

            faltante_mes = presup_mes - prod_mes_actual
            pct_ejec_mes = (prod_mes_actual / presup_mes * 100) if presup_mes > 0 else 0.0
            pronostico_ejec_pct = (pronostico_mes / presup_mes * 100) if presup_mes > 0 else 0.0
            proyectado_vs_pronostico = presup_mes - pronostico_mes
            compensacion_faltante = (proyectado_vs_pronostico / presup_mes * 100) if presup_mes > 0 else 0.0
            crec_fc_pct = ((pronostico_mes / prod_mes_previo) - 1) * 100 if prod_mes_previo > 0 else 0.0

            ultimo_dia_mes = periodo_actual + pd.offsets.MonthEnd(0)
            fecha_corte_dia = pd.Timestamp(fecha_corte).normalize()
            dias_restantes = max((ultimo_dia_mes.normalize() - fecha_corte_dia).days + 1, 0)
            req_dia_fc = (pronostico_mes - prod_mes_actual) / dias_restantes if dias_restantes > 0 else 0.0
            req_dia_pres = (presup_mes - prod_mes_actual) / dias_restantes if dias_restantes > 0 else 0.0

            resumen_lineas.append({
                'LINEA_PLUS': linea,
                previo_col: prod_mes_previo,
                actual_col: prod_mes_actual,
                'Proyectado': presup_mes,
                faltante_col: faltante_mes,
                '% Ejec.': pct_ejec_mes,
                'Pronóstico (mes)': pronostico_mes,
                'Crec. Fc (%)': crec_fc_pct,
                'Pronóstico ejecución': pronostico_ejec_pct,
                proyectado_vs_pronostico_col: proyectado_vs_pronostico,
                compensacion_col: compensacion_faltante,
                req_dia_fc_col: req_dia_fc,
                req_dia_pres_col: req_dia_pres
            })

        # ========== VISTA: AÑO ==========
        elif vista_mes == "Año":
            # Producción año anterior completo (filtrada por Quarter si aplica)
            prod_anio_previo = df_linea[
                (df_linea['FECHA'].dt.year == (ref_year - 1)) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['IMP_PRIMA'].sum()

            # Producción YTD: solo meses COMPLETADOS en el año actual (dentro del Quarter)
            prod_ytd_actual = df_linea[
                (df_linea['FECHA'].dt.year == ref_year) &
                (df_linea['FECHA'].dt.month < fecha_corte.month) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['IMP_PRIMA'].sum()

            # Producción parcial del mes actual (si está en el Quarter)
            prod_parcial_mes = (
                df_linea[df_linea['FECHA'] == periodo_actual]['IMP_PRIMA'].sum()
                if fecha_corte.month in meses_quarter else 0.0
            )

            # Presupuesto anual: usar df_filtered (no df_periodo) para incluir todos los meses del año
            df_linea_full = df_filtered[df_filtered['LINEA_PLUS'] == linea]
            presup_anual = df_linea_full[
                (df_linea_full['FECHA'].dt.year == ref_year) &
                (df_linea_full['FECHA'].dt.month.isin(meses_quarter))
            ]['PRESUPUESTO'].sum() if 'PRESUPUESTO' in df_linea_full.columns else 0.0

            serie_linea = df_linea.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
            engine_temp = ForecastEngine(conservative_factor=filters['conservative_factor'])
            serie_clean_temp = engine_temp.sanitize_series(serie_linea, ref_year)
            serie_train_temp, cur_month_temp, is_partial_temp = engine_temp.split_series_exclude_partial(
                serie_clean_temp, ref_year, fecha_corte
            )

            # Calcular steps correctos: meses restantes del año a partir del mes actual
            # last_month_temp = 0 cuando el mes parcial es enero (no hay meses completados)
            if is_partial_temp and cur_month_temp:
                last_month_temp = max(0, cur_month_temp.month - 1)
            else:
                last_month_temp = (
                    serie_train_temp.index.max().month
                    if not serie_train_temp.empty
                    else fecha_corte.month
                )
            steps_temp = max(1, 12 - last_month_temp)

            fc_result_anio = compute_line_forecast(
                serialize_series_for_cache(serie_linea),
                filters['conservative_factor'],
                ref_year,
                str(fecha_corte.date()),
                steps=steps_temp
            )

            if fc_result_anio['fc_fechas']:
                fc_fechas_ts = pd.to_datetime(fc_result_anio['fc_fechas'])
                fc_valores_list = fc_result_anio['fc_valores']

                fc_valores_list = [v * _line_adjustment_factor(linea) for v in fc_valores_list]

                is_partial_temp = fc_result_anio['is_partial']

                if is_partial_temp and fecha_corte.month in meses_quarter and fc_valores_list:
                    pronostico_mes_full_anio = fc_valores_list[0]
                    nowcast_mes = nowcast_cached(prod_parcial_mes, fecha_corte, pronostico_mes_full_anio)
                    pronostico_restante = sum(
                        v for d, v in zip(fc_fechas_ts[1:], fc_valores_list[1:])
                        if d.month in meses_quarter
                    )
                else:
                    nowcast_mes = prod_parcial_mes
                    pronostico_restante = sum(
                        v for d, v in zip(fc_fechas_ts, fc_valores_list)
                        if d.month in meses_quarter
                    )
            else:
                nowcast_mes = prod_parcial_mes
                pronostico_restante = 0.0
                is_partial_temp = False

            cierre_estimado = prod_ytd_actual + nowcast_mes + pronostico_restante
            faltante_anual = presup_anual - prod_ytd_actual
            pct_ejec_anual = (
                (prod_ytd_actual + prod_parcial_mes) / presup_anual * 100
            ) if presup_anual > 0 else 0.0
            if presup_anual <= 0:
                pronostico_ejec_pct = 0.0
            else:
                pronostico_ejec_pct = (cierre_estimado / presup_anual) * 100
            proyectado_vs_pronostico = presup_anual - cierre_estimado
            compensacion_faltante = (proyectado_vs_pronostico / presup_anual * 100) if presup_anual > 0 else 0.0
            crec_fc_pct = ((cierre_estimado / prod_anio_previo) - 1) * 100 if prod_anio_previo > 0 else 0.0

            resumen_lineas.append({
                'LINEA_PLUS': linea,
                previo_col: prod_anio_previo,
                actual_col: prod_ytd_actual,
                'Proyectado (anual)': presup_anual,
                faltante_col: faltante_anual,
                '% Ejec.': pct_ejec_anual,
                'Pronóstico (cierre)': cierre_estimado,
                'Crec. Fc (%)': crec_fc_pct,
                'Pronóstico ejecución': pronostico_ejec_pct,
                proyectado_vs_pronostico_col: proyectado_vs_pronostico,
                compensacion_col: compensacion_faltante
            })

        # ========== VISTA: ACUMULADO MES ==========
        else:
            prod_ytd_previo = df_linea[
                (df_linea['FECHA'].dt.year == (ref_year - 1)) &
                (df_linea['FECHA'].dt.month <= fecha_corte.month) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['IMP_PRIMA'].sum()

            prod_ytd_actual = df_linea[
                (df_linea['FECHA'].dt.year == ref_year) &
                (df_linea['FECHA'].dt.month <= fecha_corte.month) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['IMP_PRIMA'].sum()

            presup_ytd = df_linea[
                (df_linea['FECHA'].dt.year == ref_year) &
                (df_linea['FECHA'].dt.month <= fecha_corte.month) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['PRESUPUESTO'].sum() if 'PRESUPUESTO' in df_linea.columns else 0.0
            
            serie_linea = df_linea.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
            fc_result_acum = compute_line_forecast(
                serialize_series_for_cache(serie_linea),
                filters['conservative_factor'],
                ref_year,
                str(fecha_corte.date()),
                steps=1
            )
            pronostico_mes_full = fc_result_acum['fc_valores'][0] if fc_result_acum['fc_valores'] else 0.0
            is_partial_temp = fc_result_acum['is_partial']

            pronostico_mes_full = pronostico_mes_full * _line_adjustment_factor(linea)

            prod_meses_cerrados= df_linea[
                (df_linea['FECHA'].dt.year == ref_year) &
                (df_linea['FECHA'].dt.month < fecha_corte.month) &
                (df_linea['FECHA'].dt.month.isin(meses_quarter))
            ]['IMP_PRIMA'].sum()

            # Nowcast para el mes actual parcial
            prod_parcial_mes = df_linea[df_linea['FECHA'] == periodo_actual]['IMP_PRIMA'].sum()
            if is_partial_temp and fecha_corte.month in meses_quarter:
                pronostico_mes_actual = nowcast_cached(prod_parcial_mes, fecha_corte, pronostico_mes_full)
            else:
                pronostico_mes_actual = pronostico_mes_full if fecha_corte.month in meses_quarter else 0.0

            ytd_con_forecast = prod_meses_cerrados + pronostico_mes_actual
            faltante_ytd = presup_ytd - prod_ytd_actual
            pct_ejec_ytd = (prod_ytd_actual / presup_ytd * 100) if presup_ytd > 0 else 0.0
            pronostico_ejec_pct = (ytd_con_forecast / presup_ytd * 100) if presup_ytd > 0 else 0.0
            proyectado_vs_pronostico = presup_ytd - ytd_con_forecast
            compensacion_faltante = (proyectado_vs_pronostico / presup_ytd * 100) if presup_ytd > 0 else 0.0
            crec_fc_pct = ((ytd_con_forecast / prod_ytd_previo) - 1) * 100 if prod_ytd_previo > 0 else 0.0
             
            resumen_lineas.append({
                'LINEA_PLUS': linea,
                previo_col: prod_ytd_previo,
                actual_col: prod_ytd_actual,
                'Proyectado (YTD)': presup_ytd,
                faltante_col: faltante_ytd,
                '% Ejec.': pct_ejec_ytd,
                'Pronóstico (YTD + mes)': ytd_con_forecast,
                'Crec. Fc (%)': crec_fc_pct,
                'Pronóstico ejecución': pronostico_ejec_pct,
                proyectado_vs_pronostico_col: proyectado_vs_pronostico,
                compensacion_col: compensacion_faltante
            })
    
    df_resumen = pd.DataFrame(resumen_lineas)
    
    if not df_resumen.empty:
        st.markdown(f"**Período:** {periodo_actual.strftime('%m/%Y')}")
        st.markdown(f"**Ajuste conservador:** {filters['ajuste_pct']:.1f}%")
        if vista_mes == "Mes":
            proyectado_col = "Proyectado"
            pronostico_col = "Pronóstico (mes)"
        elif vista_mes == "Año":
            proyectado_col = "Proyectado (anual)"
            pronostico_col = "Pronóstico (cierre)"
        else:
            proyectado_col = "Proyectado (YTD)"
            pronostico_col = "Pronóstico (YTD + mes)"
        
        # Calcular totales
        totales = {}
        totales['LINEA_PLUS'] = 'TOTAL'
        
        for col in df_resumen.columns:
            if col == 'LINEA_PLUS':
                continue
            elif '% Ejec' in col or 'Crec. Fc (%)' in col or 'ejecución' in col or col == compensacion_col:
                if '% Ejec.' == col:
                    totales[col] = (df_resumen[actual_col].sum() / df_resumen[proyectado_col].sum() * 100) if df_resumen[proyectado_col].sum() > 0 else 0.0
                elif 'Pronóstico ejecución' == col:
                    totales[col] = (df_resumen[pronostico_col].sum() / df_resumen[proyectado_col].sum() * 100) if df_resumen[proyectado_col].sum() > 0 else 0.0
                elif 'Crec. Fc (%)' == col:
                    totales[col] = ((df_resumen[pronostico_col].sum() / df_resumen[previo_col].sum()) - 1) * 100 if df_resumen[previo_col].sum() > 0 else 0.0
                elif compensacion_col == col:
                    totales[col] = (df_resumen[proyectado_vs_pronostico_col].sum() / df_resumen[proyectado_col].sum() * 100) if df_resumen[proyectado_col].sum() > 0 else 0.0
            else:
                totales[col] = df_resumen[col].sum()
        
        df_resumen = pd.concat([df_resumen, pd.DataFrame([totales])], ignore_index=True)
        
        # Formatear
        df_display = df_resumen.copy()
        for col in df_display.columns:
            if col == 'LINEA_PLUS':
                continue
            elif '% Ejec' in col or 'Crec. Fc (%)' in col or 'ejecución' in col or col == compensacion_col:
                df_display[col] = df_display[col].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "-")
            else:
                df_display[col] = df_display[col].apply(lambda x: fmt_cop(x) if pd.notna(x) else "-")
        
        st.markdown("#### 📊 Resumen por Línea+")
        
        # Tabla HTML con colores
        html_table = '<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:13px;">'
        html_table += '<thead><tr style="background:#033b63;color:#fff;">'
        for col in df_display.columns:
            if col == 'LINEA_PLUS':
                display_label = 'LINEA'
            elif col.startswith('Previo'):
                display_label = col.replace('Previo', 'Producción', 1)
            elif col.startswith('Actual'):
                display_label = col.replace('Actual', 'Producción', 1)
            else:
                display_label = col
            if col == proyectado_vs_pronostico_col:
                tooltip_text = ("Diferencia entre el Presupuesto y el Pronóstico del mes. "
                                "Un valor positivo indica que el pronóstico está POR DEBAJO del presupuesto "
                                "(riesgo de no cumplir la meta). "
                                "Un valor negativo indica que el pronóstico SUPERA el presupuesto (buena señal).")
                display_label = (f'{display_label} <span title="{tooltip_text}" '
                                 'style="cursor:help;font-size:14px;opacity:0.85;">❓</span>')
            html_table += f'<th style="padding:10px;text-align:left;border-bottom:2px solid #444;">{display_label}</th>'
        html_table += '</tr></thead><tbody>'
        
        for idx, row in df_display.iterrows():
            is_total_row = (idx == len(df_display) - 1)
            row_style = 'background:rgba(56,189,248,0.1);border-top:2px solid #38bdf8;font-weight:700;' if is_total_row else 'border-bottom:1px solid rgba(255,255,255,0.05);'
            html_table += f'<tr style="{row_style}">'
            
            for col in df_display.columns:
                val = row[col]
                style = "padding:8px;"
                
                if not is_total_row:
                    if '% Ejec' in col or 'ejecución' in col:
                        try:
                            pct_val = df_resumen.iloc[idx][col]
                            if pct_val >= 100:
                                style += "color:#16a34a;font-weight:700;"
                            elif pct_val >= 95:
                                style += "color:#f59e0b;font-weight:700;"
                            else:
                                style += "color:#ef4444;font-weight:700;"
                        except:
                            pass
                    elif 'Crec. Fc' in col:
                        try:
                            if 'Crec. Fc (%)' in df_resumen.columns:
                                crec_val = df_resumen.iloc[idx]['Crec. Fc (%)']
                                style += "color:#16a34a;font-weight:700;" if crec_val >= 0 else "color:#ef4444;font-weight:700;"
                        except:
                            pass
                    elif col == faltante_col:
                        try:
                            faltante_val = df_resumen.iloc[idx][col]
                            style += "color:#16a34a;" if faltante_val <= 0 else "color:#ef4444;"
                        except:
                            pass
                    elif col in [proyectado_vs_pronostico_col, compensacion_col]:
                        try:
                            brecha_val = df_resumen.iloc[idx][col]
                            style += "color:#ef4444;font-weight:700;" if brecha_val > 0 else "color:#16a34a;font-weight:700;"
                        except:
                            pass
                
                html_table += f'<td style="{style}">{val}</td>'
            html_table += '</tr>'
        
        html_table += '</tbody></table></div>'
        st.markdown(html_table, unsafe_allow_html=True)

        st.markdown("---")
        pivot_deficit = render_deficit_heatmap_fragment(
            df_filtered=df_filtered,
            df_resumen=df_resumen,
            metric_col=proyectado_vs_pronostico_col,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            meses_quarter=tuple(meses_quarter),
            ref_year=ref_year,
            fecha_corte=fecha_corte,
        )
        pivot_faltante = render_faltante_heatmap_fragment(
            df_filtered=df_filtered,
            vista_mes=vista_mes,
            periodo_actual=periodo_actual,
            meses_quarter=tuple(meses_quarter),
            ref_year=ref_year,
            fecha_corte=fecha_corte,
        )
        df_distribution, remaining_months = render_monthly_distribution_fragment(
            df_filtered=df_filtered,
            quarter_sel=quarter_sel,
            fecha_corte=fecha_corte,
            ref_year=ref_year,
            meses_quarter=tuple(meses_quarter),
            filters=filters,
        )
        distribution_export = append_distribution_totals(df_distribution, remaining_months)

        # Exportación unificada
        with BytesIO() as buf:
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                df_resumen.to_excel(writer, sheet_name="Resumen_Lineas", index=False)
                if pivot_deficit.empty:
                    pd.DataFrame([{"Nota": "Sin datos para Deficit vs Meta con los filtros actuales"}]).to_excel(
                        writer, sheet_name="Deficit_vs_Meta", index=False
                    )
                else:
                    pivot_deficit.to_excel(writer, sheet_name="Deficit_vs_Meta")
                if pivot_faltante.empty:
                    pd.DataFrame([{"Nota": "Sin datos para Faltante proyectado con los filtros actuales"}]).to_excel(
                        writer, sheet_name="Faltante_Proyectado", index=False
                    )
                else:
                    pivot_faltante.to_excel(writer, sheet_name="Faltante_Proyectado")
                if distribution_export.empty:
                    pd.DataFrame([{"Nota": "Sin datos para Distribución Mensual con los filtros actuales"}]).to_excel(
                        writer, sheet_name="Distribucion_Mensual", index=False
                    )
                else:
                    distribution_export.to_excel(writer, sheet_name="Distribucion_Mensual", index=False)
                    _apply_increment_pct_conditional_formatting(
                        writer.book["Distribucion_Mensual"],
                        distribution_export,
                        remaining_months,
                    )
            excel_bytes = buf.getvalue()

        vista_label = {"Mes": "mes", "Año": "anio", "Acumulado Mes": "acumulado"}.get(vista_mes, "general")
        st.download_button(
            label="⬇️ Exportar resumen + mapas de calor + distribución a Excel",
            data=excel_bytes,
            file_name=f"aseguraview_{vista_label}_{periodo_actual.strftime('%Y%m')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width='stretch',
        )
    
    # Gráfico consolidado
    st.markdown("---")
    st.markdown("### 📈 Pronóstico Consolidado")
    
    prod_total = float(serie_clean.sum())
    proy_total = float(fc_df['Pronostico_mensual'].sum()) if not fc_df.empty else 0.0
    
    if filters['linea_plus'] != "TODAS":
        proy_total = proy_total * _line_adjustment_factor(filters['linea_plus'])
    
    cierre_est = prod_total + proy_total
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Producción YTD", fmt_cop(prod_total))
    col2.metric("Proyección Faltante", fmt_cop(proy_total))
    col3.metric("Cierre Estimado", fmt_cop(cierre_est))
    
    fig = render_forecast_chart(hist_df, fc_df, title=f"Pronóstico {ref_year}", accuracy_df=accuracy_df)
    st.plotly_chart(fig, width='stretch')
    
    if not fc_df.empty:
        st.markdown("##### Detalle Mensual Pronóstico")
        fc_display = fc_df.copy()
        fc_display['FECHA'] = fc_display['FECHA'].dt.strftime('%b-%Y')
        
        if filters['linea_plus'] != "TODAS":
            fc_display['Pronostico_mensual'] = fc_display['Pronostico_mensual'] * _line_adjustment_factor(filters['linea_plus'])
        
        fc_display['Pronostico_mensual'] = fc_display['Pronostico_mensual'].apply(fmt_cop)
        fc_display = fc_display.rename(columns={'Pronostico_mensual': 'Pronóstico Mensual'})
        st.dataframe(fc_display[['FECHA', 'Pronóstico Mensual']], width='stretch', hide_index=True)
    
    st.info(f"📊 SMAPE validación: {smape:.2f}%")

    # ==================== GRÁFICO DETALLADO POR LÍNEA (selector individual) ====================
    st.markdown("---")
    st.markdown("### 📈 Pronóstico Detallado por Línea")

    linea_seleccionada = st.selectbox(
        "Selecciona una línea de negocio",
        options=lineas_disponibles,
        key="selector_linea_forecast"
    )

    df_linea_sel = df_filtered[df_filtered['LINEA_PLUS'] == linea_seleccionada]

    if not df_linea_sel.empty:
        serie_linea = df_linea_sel.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()

        engine_sel = ForecastEngine(conservative_factor=filters['conservative_factor'])
        serie_clean_sel = engine_sel.sanitize_series(serie_linea, ref_year)
        serie_train_sel, _, _ = engine_sel.split_series_exclude_partial(
            serie_clean_sel, ref_year, fecha_corte
        )

        hist_sel, fc_sel, smape_sel, acc_sel = engine_sel.fit_forecast(serie_train_sel, steps=12)

        # Aplicar ajustes específicos por línea
        factor_sel = _line_adjustment_factor(linea_seleccionada)
        if factor_sel != 1.0:
            fc_sel = fc_sel.copy()
            fc_sel[['Pronostico_mensual', 'IC_lo', 'IC_hi']] = (
                fc_sel[['Pronostico_mensual', 'IC_lo', 'IC_hi']] * factor_sel
            )

        # Métricas en columnas
        col1, col2, col3, col4 = st.columns(4)
        prod_ytd = float(serie_clean_sel.sum())
        proy_restante = float(fc_sel['Pronostico_mensual'].sum())
        cierre_est_linea = prod_ytd + proy_restante

        col1.metric("Producción YTD", fmt_cop(prod_ytd))
        col2.metric("Proyección Restante", fmt_cop(proy_restante))
        col3.metric("Cierre Estimado", fmt_cop(cierre_est_linea))
        col4.metric("Precisión (SMAPE)", f"{smape_sel:.1f}%")

        fig_individual = render_forecast_chart(
            hist_sel,
            fc_sel,
            title=f"Pronóstico {linea_seleccionada} {ref_year}",
            accuracy_df=acc_sel
        )
        st.plotly_chart(fig_individual, width='stretch')

        with st.expander("📋 Ver detalle mensual del pronóstico"):
            fc_display_sel = fc_sel.copy()
            fc_display_sel['FECHA'] = fc_display_sel['FECHA'].dt.strftime('%b-%Y')
            fc_display_sel['Pronostico_mensual'] = fc_display_sel['Pronostico_mensual'].apply(fmt_cop)
            fc_display_sel['IC_lo'] = fc_display_sel['IC_lo'].apply(fmt_cop)
            fc_display_sel['IC_hi'] = fc_display_sel['IC_hi'].apply(fmt_cop)
            fc_display_sel = fc_display_sel.rename(columns={'Pronostico_mensual': 'Pronóstico Mensual'})
            st.dataframe(
                fc_display_sel[['FECHA', 'Pronóstico Mensual', 'IC_lo', 'IC_hi']],
                width='stretch',
                hide_index=True
            )
    else:
        st.info(f"No hay datos disponibles para {linea_seleccionada} con los filtros seleccionados")

    # ==================== GRÁFICO RENDIMIENTO POR SUCURSAL ====================
    st.markdown("---")

    with st.expander("💡 ¿Cómo funciona esta visualización? (Machine Learning aplicado)"):
        st.markdown("""
    ### 🤖 Análisis Predictivo de Ritmo Comercial
    
    Este gráfico utiliza **Machine Learning** y análisis de series temporales para evaluar el desempeño comercial en tiempo real.
    
    #### 🧮 ¿Cómo se calcula?
    
    1. **Días transcurridos vs días totales del mes**
       - Ejemplo: Si estamos en el día 9 de 30 → 30% del mes ha pasado
    
    2. **Ritmo esperado**
       - Si el presupuesto mensual es $100M y pasó el 30% del mes
       - Deberías llevar: $30M (30% del presupuesto)
    
    3. **Ritmo real**
       - Si la producción real es $27M
       - % Cumplimiento del ritmo = 27/30 = **90%**
    
    4. **Pronóstico SARIMAX**
       - El modelo de series temporales proyecta el cierre del mes
       - Considera estacionalidad, tendencias y patrones históricos
    
    #### 🎯 ¿Qué significan los indicadores?
    
    - 🐰⚡ **Verde (≥90%)**: Ritmo excelente, alta probabilidad de cumplir meta
    - 🐢 **Naranja (80-89%)**: Ritmo moderado, requiere atención
    - 🐢 **Rojo (<80%)**: Ritmo bajo, intervención urgente necesaria
    
    #### 📊 Ventajas del análisis ML
    
    - ✅ **Detección temprana**: Identifica problemas desde los primeros días del mes
    - ✅ **Comparación justa**: Todas las sucursales se miden con la misma métrica normalizada
    - ✅ **Acción preventiva**: Permite intervenir antes de que termine el mes
    - ✅ **Pronóstico integrado**: Combina producción real + proyección SARIMAX
    
    #### 🔍 Ordenamiento
    
    Las sucursales están ordenadas de **mayor a menor volumen de primas**, permitiendo 
    enfocar la atención en las sucursales con mayor impacto en el resultado global.
    """)

    st.markdown("### 🏢 Rendimiento por Sucursal (Ritmo Comercial)")

    if 'SUCURSAL' not in df_filtered.columns:
        st.info("📊 Filtro de sucursal no disponible en los datos")
    else:
        sucursales = sorted(df_filtered['SUCURSAL'].dropna().unique())

        rendimiento_sucursales = []
        ultimo_dia_mes_suc = periodo_actual + pd.offsets.MonthEnd(0)
        dias_totales_mes = business_days_left(periodo_actual, ultimo_dia_mes_suc)
        dias_transcurridos_mes = business_days_left(periodo_actual, fecha_corte)

        for sucursal in sucursales:
            df_suc = df_filtered[df_filtered['SUCURSAL'] == sucursal]

            prod_mes_suc = df_suc[df_suc['FECHA'] == periodo_actual]['IMP_PRIMA'].sum()
            presup_mes_suc = (
                df_suc[df_suc['FECHA'] == periodo_actual]['PRESUPUESTO'].sum()
                if 'PRESUPUESTO' in df_suc.columns else 0.0
            )

            if presup_mes_suc <= 0:
                continue

            # Ritmo: qué porcentaje del tiempo transcurrido se ha ejecutado
            ritmo_necesario = (presup_mes_suc / dias_totales_mes) * dias_transcurridos_mes if dias_totales_mes > 0 else 0
            cumplimiento_ritmo = (prod_mes_suc / ritmo_necesario * 100) if ritmo_necesario > 0 else 0

            # Pronóstico para la sucursal
            serie_suc = df_suc.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
            serie_data_suc = (
                tuple(str(d) for d in serie_suc.index),
                tuple(float(v) for v in serie_suc.values),
            )
            fc_suc_result = compute_line_forecast(
                serie_data_suc,
                filters['conservative_factor'],
                ref_year,
                str(fecha_corte.date()),
                steps=1
            )

            pronostico_suc = fc_suc_result['fc_valores'][0] if fc_suc_result['fc_valores'] else 0.0
            if fc_suc_result.get('is_partial'):
                pronostico_suc = nowcast_cached(prod_mes_suc, fecha_corte, pronostico_suc)

            pronostico_ejec_suc = (pronostico_suc / presup_mes_suc * 100) if presup_mes_suc > 0 else 0

            if cumplimiento_ritmo >= _UMBRAL_BUEN_RITMO:
                indicador = _INDICADOR_BUEN_RITMO
                color_barra = _COLOR_BUEN_RITMO
            elif cumplimiento_ritmo >= _UMBRAL_RITMO_MEDIO:
                indicador = _INDICADOR_RITMO_LENTO
                color_barra = _COLOR_RITMO_MEDIO
            else:
                indicador = _INDICADOR_RITMO_LENTO
                color_barra = _COLOR_RITMO_LENTO

            rendimiento_sucursales.append({
                'Sucursal': f"{indicador} {sucursal}",
                'Producción': prod_mes_suc,
                'Presupuesto': presup_mes_suc,
                '% Avance': (prod_mes_suc / presup_mes_suc * 100),
                'Ritmo (%)': cumplimiento_ritmo,
                'Pronóstico': pronostico_suc,
                'Pronóstico %': pronostico_ejec_suc,
                'Color': color_barra
            })

        if rendimiento_sucursales:
            df_rend = pd.DataFrame(rendimiento_sucursales)
            df_rend = df_rend.sort_values('Producción', ascending=True)

            fig_suc = go.Figure()

            fig_suc.add_trace(go.Bar(
                y=df_rend['Sucursal'],
                x=df_rend['Ritmo (%)'],
                orientation='h',
                marker=dict(color=df_rend['Color']),
                text=df_rend['Ritmo (%)'].apply(lambda x: f"{x:.1f}%"),
                textposition='outside',
                customdata=df_rend[['Producción', 'Presupuesto', 'Pronóstico', 'Pronóstico %']].values,
                hovertemplate=(
                    '<b>%{y}</b><br>'
                    'Producción: $%{customdata[0]:,.0f}<br>'
                    'Presupuesto: $%{customdata[1]:,.0f}<br>'
                    'Ritmo: %{x:.1f}%<br>'
                    'Pronóstico: $%{customdata[2]:,.0f}<br>'
                    'Pronóstico Ejec.: %{customdata[3]:.1f}%'
                    '<extra></extra>'
                )
            ))

            fig_suc.add_vline(x=100, line_dash="dash", line_color="white", opacity=0.5)

            fig_suc.update_layout(
                title="Ritmo Comercial por Sucursal (🐰⚡ = Buen ritmo, 🐢 = Ritmo lento)",
                xaxis_title="% Cumplimiento del Ritmo Necesario",
                yaxis_title="",
                template="plotly_dark",
                height=max(400, len(df_rend) * 40),
                showlegend=False,
                margin=dict(l=10, r=10, t=40, b=10),
            )

            st.plotly_chart(fig_suc, width='stretch')
            st.caption("💡 El 100% indica que la sucursal lleva el ritmo exacto para cumplir el presupuesto mensual")
        else:
            st.info("No hay datos de sucursales para mostrar con los filtros seleccionados")

# ========== TAB 3: FIANZAS ==========
with tabs[2]:
    st.subheader("🏛️ Análisis FIANZAS")
    
    df_fianzas = df[df['LINEA_PLUS'] == 'FIANZAS'] if 'LINEA_PLUS' in df.columns else pd.DataFrame()
    
    if df_fianzas.empty:
        st.warning("No hay datos de FIANZAS disponibles")
    else:
        adjuster = FianzasAdjuster(usar_segunda_vuelta=True)
        
        st.markdown("#### 📅 Calendario de Impacto 2026")
        impact_df = adjuster.get_impact_summary(2026)
        st.dataframe(impact_df, width='stretch', hide_index=True)
        
        with st.expander("Ver calendario visual"):
            st.code(adjuster.get_calendar_visual(2026), language=None)
        
        st.markdown("#### 📈 Pronóstico de FIANZAS Ajustado")
        
        serie_fianzas = df_fianzas.groupby('FECHA')['IMP_PRIMA'].sum().sort_index()
        
        if not serie_fianzas.empty:
            engine_fianzas = ForecastEngine(conservative_factor=filters['conservative_factor'])
            serie_clean_f = engine_fianzas.sanitize_series(serie_fianzas, filters['anio_analisis'])
            serie_train_f, _, _ = engine_fianzas.split_series_exclude_partial(
                serie_clean_f, filters['anio_analisis'], fecha_corte
            )
            
            hist_f, fc_f, _, _ = engine_fianzas.fit_forecast(serie_train_f, steps=12)
            
            if not fc_f.empty:
                fc_adjusted = adjuster.adjust_forecast(fc_f['Pronostico_mensual'], fc_f['FECHA'])
                fc_f['Pronostico_ajustado_garantias'] = fc_adjusted
                fc_f['Diferencia'] = fc_f['Pronostico_ajustado_garantias'] - fc_f['Pronostico_mensual']
            
            fc_display_f = fc_f.copy()
            fc_display_f['FECHA'] = fc_display_f['FECHA'].dt.strftime('%b-%Y')
            fc_display_f['Pronostico_mensual'] = fc_display_f['Pronostico_mensual'].apply(fmt_cop)
            fc_display_f['Pronostico_ajustado_garantias'] = fc_display_f['Pronostico_ajustado_garantias'].apply(fmt_cop)
            fc_display_f['Diferencia'] = fc_display_f['Diferencia'].apply(fmt_cop)
            fc_display_f = fc_display_f.rename(columns={
                'Pronostico_mensual': 'Pronóstico Mensual',
                'Pronostico_ajustado_garantias': 'Pronóstico Ajustado Garantías',
            })
            
            st.dataframe(fc_display_f[['FECHA', 'Pronóstico Mensual', 'Pronóstico Ajustado Garantías', 'Diferencia']], 
                        width='stretch', hide_index=True)

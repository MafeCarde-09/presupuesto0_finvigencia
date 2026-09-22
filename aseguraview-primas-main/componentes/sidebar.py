# -*- coding: utf-8 -*-
"""
Componente de sidebar con filtros
"""
import streamlit as st
import pandas as pd


def render_sidebar(df: pd.DataFrame, fecha_corte: pd.Timestamp) -> dict:
    """
    Renderiza sidebar con filtros: Línea+, Código, Sucursal, Sucursal Agrupada y ajustes de pronóstico.
    """
    st.sidebar.header("🔍 Filtros")

    lineas_opts = ["TODAS"]
    if 'LINEA_PLUS' in df.columns:
        lineas_opts += sorted(df['LINEA_PLUS'].dropna().unique())

    linea_selected = st.sidebar.selectbox(
        "Línea +",
        lineas_opts,
        help="Filtra por línea de negocio principal"
    )

    # ── Filtro Código ────────────────────────────────────────────────────────
    codigos_selected = []
    if 'CODIGO' in df.columns:
        codigos_opts = sorted(df['CODIGO'].dropna().unique().tolist())
        codigos_selected = st.sidebar.multiselect(
            "Código",
            options=codigos_opts,
            default=[],
            help="Filtra por código de producto"
        )
    else:
        st.sidebar.caption("ℹ️ Columna CODIGO no disponible en los datos.")

    # ── Filtro Sucursal ──────────────────────────────────────────────────────
    sucursales_selected = []
    if 'SUCURSAL' in df.columns:
        sucursales_opts = sorted(df['SUCURSAL'].dropna().unique().tolist())
        sucursales_selected = st.sidebar.multiselect(
            "Sucursal",
            options=sucursales_opts,
            default=[],
            help="Filtra por sucursal"
        )
    else:
        st.sidebar.caption("ℹ️ Columna SUCURSAL no disponible en los datos.")

    # ── Filtro Sucursal Agrupada ─────────────────────────────────────────────
    suc_agrupadas_selected = []
    if 'Suc_agrupada' in df.columns:
        suc_agrupadas_opts = sorted(df['Suc_agrupada'].dropna().unique().tolist())
        suc_agrupadas_selected = st.sidebar.multiselect(
            "Sucursal Agrupada",
            options=suc_agrupadas_opts,
            default=suc_agrupadas_opts,
            key="filtro_suc_agrupada",
            help="Filtra por sucursal agrupada"
        )
    else:
        st.sidebar.caption("ℹ️ Columna Suc_agrupada no disponible en los datos.")

    anio_analisis = st.sidebar.number_input(
        "Año de análisis",
        min_value=2018,
        max_value=2100,
        value=fecha_corte.year,
        step=1,
        help="Año para realizar el análisis y pronósticos"
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### ⚙️ Ajustes de Pronóstico")

    ajuste_pct = st.sidebar.slider(
        "Ajuste conservador (%)",
        min_value=-20.0,
        max_value=10.0,
        step=0.5,
        value=0.0,
        help="Porcentaje de ajuste aplicado a las proyecciones"
    )

    nota_ajuste = st.sidebar.text_input(
        "Nota del ajuste (opcional)",
        value="",
        help="Comentario sobre el ajuste realizado"
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### 📅 Información")
    st.sidebar.info(f"**Fecha de corte:**\n{fecha_corte.strftime('%d/%m/%Y')}")

    return {
        'linea_plus': linea_selected,
        'codigos': codigos_selected,
        'sucursales': sucursales_selected,
        'suc_agrupadas': suc_agrupadas_selected,
        'anio_analisis': int(anio_analisis),
        'ajuste_pct': float(ajuste_pct),
        'nota_ajuste': nota_ajuste,
        'conservative_factor': 1.0 + (ajuste_pct / 100.0)
    }

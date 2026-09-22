# -*- coding: utf-8 -*-
"""
Tarjetas de resumen con métricas principales
"""
import streamlit as st


def render_summary_cards(metrics: dict):
    """Renderiza tarjetas de resumen en formato vertical"""
    
    html = '<div class="table-wrap"><div class="vertical-summary"><div class="vert-left card">'
    
    for label, value in metrics.items():
        html += f'<div class="vrow"><div class="vtitle">{label}</div><div class="vvalue">{value}</div></div>'
    
    html += '</div>'
    
    if 'nota_ajuste' in metrics and metrics['nota_ajuste']:
        html += f'<div class="vert-right card"><div class="small">📝 {metrics["nota_ajuste"]}</div></div>'
    
    html += '</div></div>'
    
    st.markdown(html, unsafe_allow_html=True)

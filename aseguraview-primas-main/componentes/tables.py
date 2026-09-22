# -*- coding: utf-8 -*-
"""
Componente para renderizar tablas HTML estilizadas
"""
import pandas as pd


def df_to_html(df: pd.DataFrame) -> str:
    """Convierte DataFrame a HTML estilizado"""
    if df.empty:
        return '<div class="card"><p class="muted">No hay datos disponibles</p></div>'
    
    html = '<div class="table-wrap"><table class="tbl"><thead><tr>'
    
    for col in df.columns:
        html += f'<th>{col}</th>'
    
    html += '</tr></thead><tbody>'
    
    for _, row in df.iterrows():
        html += '<tr>'
        for col in df.columns:
            html += f'<td>{row[col]}</td>'
        html += '</tr>'
    
    html += '</tbody></table></div>'
    
    return html

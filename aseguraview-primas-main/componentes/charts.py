# -*- coding: utf-8 -*-
"""
Componente para gráficos Plotly
"""
import pandas as pd
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import plotly.graph_objects as go


def render_forecast_chart(hist_df: pd.DataFrame,
                          forecast_df: pd.DataFrame,
                          title: str = "Pronóstico de Primas",
                          accuracy_df: pd.DataFrame = None) -> Any:
    """Genera gráfico de pronóstico con histórico, predicción y precisión histórica.

    Args:
        hist_df: DataFrame con columnas FECHA y Mensual (histórico real).
        forecast_df: DataFrame con columnas FECHA y Pronostico_mensual (pronósticos futuros).
        title: Título del gráfico.
        accuracy_df: DataFrame opcional con columnas FECHA, Real y Forecast_hist.
                     Si se proporciona, se añade una línea de precisión del modelo
                     mostrando pronóstico histórico vs real (últimos 6-12 meses validados).
    """
    try:
        import plotly.graph_objects as go
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "plotly no está instalado. Ejecuta `pip install -r requirements.txt` para habilitar los gráficos."
        ) from exc

    fig = go.Figure()

    if not hist_df.empty and 'FECHA' in hist_df.columns and 'Mensual' in hist_df.columns:
        fig.add_trace(go.Scatter(
            x=hist_df['FECHA'],
            y=hist_df['Mensual'],
            mode='lines',
            name='Histórico',
            line=dict(color='#38bdf8', width=2)
        ))

    if not forecast_df.empty and 'FECHA' in forecast_df.columns and 'Pronostico_mensual' in forecast_df.columns:
        fig.add_trace(go.Scatter(
            x=forecast_df['FECHA'],
            y=forecast_df['Pronostico_mensual'],
            mode='lines+markers',
            name='Pronóstico',
            line=dict(color='#f59e0b', width=2, dash='dash')
        ))

        if 'IC_hi' in forecast_df.columns and 'IC_lo' in forecast_df.columns:
            fig.add_trace(go.Scatter(
                x=forecast_df['FECHA'],
                y=forecast_df['IC_hi'],
                mode='lines',
                line=dict(width=0),
                showlegend=False,
                hoverinfo='skip'
            ))

            fig.add_trace(go.Scatter(
                x=forecast_df['FECHA'],
                y=forecast_df['IC_lo'],
                mode='lines',
                fill='tonexty',
                fillcolor='rgba(245, 158, 11, 0.2)',
                line=dict(width=0),
                name='IC 95%',
                hoverinfo='skip'
            ))

    # ── Línea de precisión histórica (Pronóstico vs Real) ──────────────────────
    if accuracy_df is not None and not accuracy_df.empty:
        required_cols = {'FECHA', 'Real', 'Forecast_hist'}
        if required_cols.issubset(accuracy_df.columns):
            acc = accuracy_df.copy()
            acc = acc.sort_values('FECHA').tail(12)  # Mostrar últimos 12 meses validados

            # Calcular error porcentual para color condicional
            acc['error_pct'] = (
                (acc['Forecast_hist'] - acc['Real']).abs()
                / acc['Real'].replace(0, float('nan'))
                * 100
            ).fillna(0)

            # Línea de pronóstico histórico validado
            fig.add_trace(go.Scatter(
                x=acc['FECHA'],
                y=acc['Forecast_hist'],
                mode='lines+markers',
                name='Pronóstico histórico',
                line=dict(color='#a78bfa', width=1.5, dash='dot'),
                marker=dict(size=6, symbol='diamond'),
                customdata=acc[['Real', 'error_pct']].values,
                hovertemplate=(
                    'Mes: %{x|%b-%Y}<br>'
                    'Pronóstico: %{y:,.0f}<br>'
                    'Real: %{customdata[0]:,.0f}<br>'
                    'Error: ±%{customdata[1]:.1f}%'
                    '<extra>Pronóstico histórico</extra>'
                )
            ))

            # Puntos de la serie real del período validado (marcadores de color)
            fig.add_trace(go.Scatter(
                x=acc['FECHA'],
                y=acc['Real'],
                mode='markers',
                name='Real (validación)',
                marker=dict(
                    size=8,
                    color=acc['error_pct'].apply(
                        lambda e: '#16a34a' if e <= 10 else ('#f59e0b' if e <= 20 else '#ef4444')
                    ),
                    symbol='circle',
                    line=dict(color='white', width=1)
                ),
                customdata=acc[['Forecast_hist', 'error_pct']].values,
                hovertemplate=(
                    'Mes: %{x|%b-%Y}<br>'
                    'Real: %{y:,.0f}<br>'
                    'Pronóstico: %{customdata[0]:,.0f}<br>'
                    'Error: ±%{customdata[1]:.1f}%'
                    '<extra>Real (validación)</extra>'
                )
            ))

    fig.update_layout(
        title=title,
        xaxis_title="Fecha",
        yaxis_title="COP",
        hovermode='x unified',
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis=dict(
            rangeslider=dict(visible=True),
            type="date"
        ),
        template="plotly_dark"
    )

    return fig

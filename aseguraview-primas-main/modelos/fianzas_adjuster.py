# -*- coding: utf-8 -*-
"""
Ajustador de pronósticos para FIANZAS considerando Ley de Garantías
"""
import pandas as pd
import numpy as np
from config import LEY_GARANTIAS_2026, ADJUSTMENT_FACTORS


class FianzasAdjuster:
    """
    Ajusta pronósticos de FIANZAS considerando Ley de Garantías.
    
    Ley de Garantías Colombia 2026:
    - Inicio: 31 enero 2026
    - Fin (1ra vuelta): 24 mayo 2026
    - Fin (2da vuelta): 21 junio 2026
    """
    
    def __init__(self, usar_segunda_vuelta: bool = None):
        self.config = LEY_GARANTIAS_2026.copy()
        
        if usar_segunda_vuelta is None:
            usar_segunda_vuelta = self.config['usar_segunda_vuelta']
        
        self.usar_segunda_vuelta = usar_segunda_vuelta
        
        if usar_segunda_vuelta:
            self.fecha_fin_garantias = pd.Timestamp(self.config['fin_segunda_vuelta'])
        else:
            self.fecha_fin_garantias = pd.Timestamp(self.config['fin_primera_vuelta'])
        
        self.fecha_inicio_garantias = pd.Timestamp(self.config['inicio'])
    
    def get_periodo_fase(self, fecha: pd.Timestamp) -> dict:
        """Determina en qué fase de Ley de Garantías está una fecha"""
        inicio = self.fecha_inicio_garantias
        fin = self.fecha_fin_garantias
        
        meses_pre = ADJUSTMENT_FACTORS['pre_garantias']['meses_antes']
        pre_inicio = inicio - pd.DateOffset(months=meses_pre)
        
        if pre_inicio <= fecha < inicio:
            return {
                'fase': 'pre_garantias',
                'factor': ADJUSTMENT_FACTORS['pre_garantias']['factor'],
                'descripcion': ADJUSTMENT_FACTORS['pre_garantias']['descripcion']
            }
        
        if inicio <= fecha <= fin:
            return {
                'fase': 'garantias_activa',
                'factor': ADJUSTMENT_FACTORS['garantias_activa']['factor'],
                'descripcion': ADJUSTMENT_FACTORS['garantias_activa']['descripcion']
            }
        
        meses_post = ADJUSTMENT_FACTORS['post_garantias']['meses_despues']
        post_fin = fin + pd.DateOffset(months=meses_post)
        
        if fin < fecha <= post_fin:
            return {
                'fase': 'post_garantias',
                'factor': ADJUSTMENT_FACTORS['post_garantias']['factor'],
                'descripcion': ADJUSTMENT_FACTORS['post_garantias']['descripcion']
            }
        
        meses_rec = ADJUSTMENT_FACTORS['recuperacion']['meses_despues']
        recuperacion_fin = post_fin + pd.DateOffset(months=meses_rec)
        
        if post_fin < fecha <= recuperacion_fin:
            return {
                'fase': 'recuperacion',
                'factor': ADJUSTMENT_FACTORS['recuperacion']['factor'],
                'descripcion': ADJUSTMENT_FACTORS['recuperacion']['descripcion']
            }
        
        return {
            'fase': 'normal',
            'factor': 1.0,
            'descripcion': 'Operación normal sin restricciones'
        }
    
    def adjust_forecast(self, base_forecast: pd.Series, 
                       forecast_dates: pd.DatetimeIndex) -> pd.Series:
        """Aplica ajustes de Ley de Garantías a pronóstico de FIANZAS"""
        adjusted = pd.Series(index=forecast_dates, dtype=float)
        
        for i, fecha in enumerate(forecast_dates):
            fase_info = self.get_periodo_fase(fecha)
            factor = fase_info['factor']
            
            base_value = base_forecast.iloc[i] if i < len(base_forecast) else 0.0
            adjusted[fecha] = base_value * factor
        
        return adjusted
    
    def get_impact_summary(self, year: int = 2026) -> pd.DataFrame:
        """Genera resumen del impacto de Ley de Garantías por mes"""
        meses = pd.date_range(f'{year}-01-01', f'{year}-12-31', freq='MS')
        
        rows = []
        for fecha in meses:
            fase_info = self.get_periodo_fase(fecha)
            factor = fase_info['factor']
            
            if factor < 1.0:
                impacto = f"{(1 - factor) * 100:.0f}% reducción"
                emoji = "⚠️" if factor < 0.5 else "📉"
            elif factor > 1.0:
                impacto = f"+{(factor - 1) * 100:.0f}% incremento"
                emoji = "🚀"
            else:
                impacto = "Sin cambio"
                emoji = "✅"
            
            rows.append({
                'Mes': fecha.strftime('%B %Y'),
                'Fase': f"{emoji} {fase_info['fase'].replace('_', ' ').title()}",
                'Factor Ajuste': f"{factor:.0%}",
                'Impacto': impacto,
                'Descripción': fase_info['descripcion']
            })
        
        return pd.DataFrame(rows)
    
    def get_calendar_visual(self, year: int = 2026) -> str:
        """Genera calendario visual en texto del impacto"""
        df = self.get_impact_summary(year)
        
        lines = []
        lines.append("┌─────────────┬──────────────────────┬──────────┬─────────────────────┐")
        lines.append("│    Mes      │        Fase          │  Factor  │     Impacto         │")
        lines.append("├─────────────┼──────────────────────┼──────────┼─────────────────────┤")
        
        for _, row in df.iterrows():
            mes = row['Mes'][:8].ljust(11)
            fase = row['Fase'][:20].ljust(20)
            factor = row['Factor Ajuste'].ljust(8)
            impacto = row['Impacto'][:19].ljust(19)
            
            lines.append(f"│ {mes} │ {fase} │ {factor} │ {impacto} │")
        
        lines.append("└─────────────┴──────────────────────┴──────────┴─────────────────────┘")
        
        return "\n".join(lines)

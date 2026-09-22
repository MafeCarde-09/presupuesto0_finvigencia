# -*- coding: utf-8 -*-
"""
Generador de presupuesto 2026 desagregado
"""
import pandas as pd
import numpy as np

try:
    from xgboost import XGBRegressor
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False


class Budget2026Generator:
    """Genera presupuesto 2026 desagregado por LINEA_PLUS usando XGBoost"""
    
    def __init__(self, conservative_factor: float = 1.0, ipc_adjustment: float = 0.0):
        self.conservative_factor = conservative_factor
        self.ipc_adjustment = ipc_adjustment
    
    def prepare_segment_data(self, df_segment: pd.DataFrame) -> pd.DataFrame:
        """Prepara dataset agregado por fecha"""
        df = df_segment.copy()
        
        if 'FECHA' not in df.columns:
            return pd.DataFrame(columns=['FECHA', 'IMP_PRIMA', 'YEAR', 'MONTH'])
        
        df['FECHA'] = pd.to_datetime(df['FECHA'], errors='coerce')
        df = df.dropna(subset=['FECHA'])
        
        if 'IMP_PRIMA' in df.columns:
            df['IMP_PRIMA'] = pd.to_numeric(df['IMP_PRIMA'], errors='coerce').fillna(0)
        else:
            df['IMP_PRIMA'] = 0.0
        
        agg = df.groupby('FECHA')['IMP_PRIMA'].sum().sort_index().reset_index()
        
        if agg.empty:
            return pd.DataFrame(columns=['FECHA', 'IMP_PRIMA', 'YEAR', 'MONTH'])
        
        agg['YEAR'] = agg['FECHA'].dt.year
        agg['MONTH'] = agg['FECHA'].dt.month
        
        return agg
    
    def forecast_segment(self, df_segment: pd.DataFrame, target_year: int = 2026) -> float:
        """Genera pronóstico anual para un segmento usando XGBoost o promedio"""
        agg = self.prepare_segment_data(df_segment)
        
        if len(agg) < 3:
            total = float(agg['IMP_PRIMA'].sum()) if 'IMP_PRIMA' in agg.columns else 0.0
            return total * self.conservative_factor
        
        X_hist = agg[['YEAR', 'MONTH']].values
        y_hist = agg['IMP_PRIMA'].values
        
        fut = pd.DataFrame({
            'YEAR': [target_year] * 12,
            'MONTH': list(range(1, 13))
        })
        X_fut = fut[['YEAR', 'MONTH']].values
        
        if XGBOOST_AVAILABLE and len(np.unique(y_hist)) > 1:
            try:
                model = XGBRegressor(
                    n_estimators=200,
                    learning_rate=0.07,
                    max_depth=4,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42
                )
                model.fit(X_hist, y_hist)
                y_pred = model.predict(X_fut)
                y_pred = np.where(y_pred < 0, 0, y_pred)
                
                total_forecast = float(np.sum(y_pred))
                return total_forecast * self.conservative_factor
            
            except Exception:
                pass
        
        last_6 = agg.tail(6)['IMP_PRIMA']
        base_monthly = last_6.mean() if len(last_6) > 0 else agg['IMP_PRIMA'].mean()
        
        return float(base_monthly * 12 * self.conservative_factor)
    
    def generate_budget_table(self, df: pd.DataFrame, target_year: int = 2026) -> pd.DataFrame:
        """Genera tabla de presupuesto desagregado por LINEA_PLUS"""
        if 'LINEA_PLUS' not in df.columns:
            return pd.DataFrame()
        
        lineas = sorted(df['LINEA_PLUS'].dropna().unique())
        rows = []
        
        for linea in lineas:
            df_linea = df[df['LINEA_PLUS'] == linea]
            
            forecast_base = self.forecast_segment(df_linea, target_year)
            
            ipc_factor = 1.0 + (self.ipc_adjustment / 100.0)
            forecast_adjusted = forecast_base * ipc_factor
            
            rows.append({
                'LINEA_PLUS': linea,
                f'Presupuesto_{target_year}_Base': round(forecast_base, 0),
                f'Presupuesto_{target_year}_Ajustado_IPC': round(forecast_adjusted, 0),
                'IPC_Aplicado': f"{self.ipc_adjustment:.1f}%",
                'Modelo': 'XGBoost mensual' if XGBOOST_AVAILABLE else 'Promedio 6m x12'
            })
        
        return pd.DataFrame(rows)

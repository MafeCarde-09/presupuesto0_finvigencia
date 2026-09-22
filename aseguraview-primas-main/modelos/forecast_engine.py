# -*- coding: utf-8 -*-
"""
Motor de pronósticos usando SARIMAX/ARIMA
"""
import pandas as pd
import numpy as np
import warnings
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.arima.model import ARIMA
from utils.date_utils import ensure_monthly, business_days_left, get_month_range

warnings.filterwarnings("ignore")


class ForecastEngine:
    """Motor de pronósticos para series temporales de primas"""
    
    def __init__(self, conservative_factor: float = 1.0):
        self.conservative_factor = conservative_factor
    
    def sanitize_series(self, ts: pd.Series, ref_year: int) -> pd.Series:
        """Limpia serie eliminando ceros finales del año de referencia"""
        ts = ensure_monthly(ts.copy())
        year_series = ts[ts.index.year == ref_year]
        
        if year_series.empty:
            return ts.dropna()
        
        mask = (year_series[::-1] == 0)
        run, flag = [], True
        for v in mask:
            if flag and bool(v):
                run.append(True)
            else:
                flag = False
                run.append(False)
        
        trailing_zeros = pd.Series(run[::-1], index=year_series.index)
        ts.loc[trailing_zeros.index[trailing_zeros]] = np.nan
        
        if ts.last_valid_index() is not None:
            ts = ts.loc[:ts.last_valid_index()]
        
        return ts.dropna()
    
    def split_series_exclude_partial(self, ts: pd.Series, ref_year: int, 
                                     cutoff_date: pd.Timestamp) -> tuple:
        """Separa serie excluyendo mes parcial actual"""
        ts = ensure_monthly(ts.copy())
        cur_month = pd.Timestamp(year=cutoff_date.year, month=cutoff_date.month, day=1)
        
        if len(ts) == 0:
            return ts, None, False
        
        end_of_month = (cur_month + pd.offsets.MonthEnd(0)).day
        
        if cutoff_date.day < end_of_month:
            ts.loc[cur_month] = np.nan
            return ts.dropna(), cur_month, True
        
        return ts.dropna(), None, False
    
    def smape(self, y_true, y_pred) -> float:
        """Calcula Symmetric Mean Absolute Percentage Error"""
        y_true = np.array(y_true, dtype=float)
        y_pred = np.array(y_pred, dtype=float)
        
        numerator = np.abs(y_pred - y_true)
        denominator = (np.abs(y_true) + np.abs(y_pred) + 1e-9)
        
        return np.mean(2.0 * numerator / denominator) * 100
    
    def nowcast(self, prod_parcial: float, fecha_corte: pd.Timestamp,
                forecast_mes_completo: float) -> float:
        """
        Calcula nowcast dinámico para el mes actual.

        Toma la producción parcial acumulada hasta fecha_corte y proyecta
        los días hábiles restantes usando la proporción del pronóstico original.

        Fórmula: nowcast = prod_parcial + pronostico_completo * (días_restantes / días_totales)

        Args:
            prod_parcial: Producción real acumulada hasta fecha_corte
            fecha_corte: Fecha de corte de los datos (puede ser intramensual)
            forecast_mes_completo: Pronóstico SARIMAX para el mes completo

        Returns:
            Nowcast ajustado para el mes
        """
        primer_dia, ultimo_dia = get_month_range(fecha_corte.year, fecha_corte.month)
        dias_totales = business_days_left(primer_dia, ultimo_dia)
        dias_restantes = business_days_left(fecha_corte, ultimo_dia)

        if dias_totales <= 0:
            return prod_parcial

        proporcion_restante = dias_restantes / dias_totales
        return prod_parcial + forecast_mes_completo * proporcion_restante

    def fit_forecast(self, ts: pd.Series, steps: int, eval_months: int = 6) -> tuple:
        """Ajusta modelo SARIMAX/ARIMA y genera pronóstico.

        Returns:
            Tuple de (hist_df, forecast_df, smape_validation, accuracy_df) donde
            accuracy_df contiene los pronósticos históricos rolling vs real.
        """
        if steps < 1:
            steps = 1
        
        ts = ensure_monthly(ts.copy())
        
        if ts.empty:
            empty_hist = pd.DataFrame(columns=["FECHA", "Mensual", "ACUM"])
            empty_fc = pd.DataFrame(columns=[
                "FECHA", "Pronostico_mensual", "Pronostico_acum", "IC_lo", "IC_hi"
            ])
            empty_acc = pd.DataFrame(columns=["FECHA", "Real", "Forecast_hist"])
            return empty_hist, empty_fc, np.nan, empty_acc
        
        y = np.log1p(ts)
        
        smapes = []
        accuracy_data = []
        start = max(len(y) - eval_months, 12)
        
        if len(y) >= start + 1:
            for t in range(start, len(y)):
                y_train = y.iloc[:t]
                y_test = y.iloc[t:t+1]
                real_value = float(np.expm1(y_test.values[0]))
                
                try:
                    model = SARIMAX(
                        y_train,
                        order=(1, 1, 1),
                        seasonal_order=(1, 1, 1, 12),
                        enforce_stationarity=False,
                        enforce_invertibility=False
                    )
                    result = model.fit(disp=False)
                    pred = result.get_forecast(steps=1).predicted_mean
                except Exception:
                    model = ARIMA(y_train, order=(1, 1, 1))
                    result = model.fit()
                    pred = result.get_forecast(steps=1).predicted_mean
                
                pred_value = float(np.expm1(pred.values[0])) * self.conservative_factor
                smapes.append(self.smape(
                    np.array([real_value]),
                    np.array([pred_value])
                ))
                accuracy_data.append({
                    'FECHA': ts.index[t],
                    'Real': real_value,
                    'Forecast_hist': pred_value
                })
        
        smape_validation = float(np.mean(smapes)) if smapes else np.nan
        accuracy_df = (
            pd.DataFrame(accuracy_data)
            if accuracy_data
            else pd.DataFrame(columns=["FECHA", "Real", "Forecast_hist"])
        )
        
        def apply_adjustment(arr):
            return np.expm1(arr) * self.conservative_factor
        
        try:
            model_full = SARIMAX(
                y,
                order=(1, 1, 1),
                seasonal_order=(1, 1, 1, 12),
                enforce_stationarity=False,
                enforce_invertibility=False
            )
            result_full = model_full.fit(disp=False)
            forecast = result_full.get_forecast(steps=steps)
            
            mean_forecast = apply_adjustment(forecast.predicted_mean)
            conf_int = np.expm1(forecast.conf_int(alpha=0.05)) * self.conservative_factor
        
        except Exception:
            model_full = ARIMA(y, order=(1, 1, 1))
            result_full = model_full.fit()
            forecast = result_full.get_forecast(steps=steps)
            
            mean_forecast = apply_adjustment(forecast.predicted_mean)
            conf_int = np.expm1(forecast.conf_int(alpha=0.05)) * self.conservative_factor
        
        future_dates = pd.date_range(
            ts.index.max() + pd.offsets.MonthBegin(),
            periods=steps,
            freq="MS"
        )
        
        hist_acum = ts.cumsum()
        hist_df = pd.DataFrame({
            "FECHA": ts.index,
            "Mensual": ts.values,
            "ACUM": hist_acum.values if len(ts) > 0 else []
        })
        
        forecast_acum = np.cumsum(mean_forecast) + (
            hist_acum.iloc[-1] if len(hist_acum) > 0 else 0.0
        )
        
        forecast_df = pd.DataFrame({
            "FECHA": future_dates,
            "Pronostico_mensual": mean_forecast.values.clip(min=0),
            "Pronostico_acum": forecast_acum.values.clip(min=0),
            "IC_lo": conf_int.iloc[:, 0].values.clip(min=0),
            "IC_hi": conf_int.iloc[:, 1].values.clip(min=0)
        })
        
        return hist_df, forecast_df, smape_validation, accuracy_df

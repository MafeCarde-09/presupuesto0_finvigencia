# -*- coding: utf-8 -*-
"""
Formateo de números y HTML
"""
import pandas as pd


def fmt_cop(x) -> str:
    """Formatea número como COP"""
    try:
        return "$" + f"{int(round(float(x))):,}".replace(",", ".")
    except Exception:
        return str(x)


def pct_plain(val) -> str:
    """Formatea porcentaje sin HTML"""
    try:
        if pd.isna(val):
            return "-"
        return f"{float(val):.1f}%"
    except Exception:
        return "-"


def badge_pct_html(val) -> str:
    """Formatea porcentaje con color"""
    try:
        if pd.isna(val):
            return "-"
        f = float(val)
    except Exception:
        return "-"
    
    if f >= 100:
        cls = "ok"
    elif f >= 95:
        cls = "near"
    else:
        cls = "bad"
    
    return f'<span class="{cls}">{f:.1f}%</span>'


def badge_growth_cop_html(val) -> str:
    """Formatea crecimiento en COP con color"""
    try:
        if pd.isna(val):
            return "-"
        f = float(val)
    except Exception:
        return "-"
    
    cls = "ok" if f >= 0 else "bad"
    return f'<span class="{cls}">{fmt_cop(f)}</span>'


def badge_growth_pct_html(val) -> str:
    """Formatea crecimiento en % con color"""
    try:
        if pd.isna(val):
            return "-"
        f = float(val)
    except Exception:
        return "-"
    
    cls = "ok" if f >= 0 else "bad"
    return f'<span class="{cls}">{f:.1f}%</span>'


def badge_growth_html(val_cop, val_pct) -> str:
    """Formatea crecimiento COP + %"""
    cop_str = badge_growth_cop_html(val_cop)
    pct_str = badge_growth_pct_html(val_pct)
    return f"{cop_str} ({pct_str})"

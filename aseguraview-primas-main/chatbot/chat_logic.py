# -*- coding: utf-8 -*-
"""
Lógica de IA y contexto del dashboard para el chatbot de AseguraView
"""
import streamlit as st
from typing import Any

from .prompts import SYSTEM_PROMPT_TEMPLATE


def build_context(
    fecha_corte: Any,
    filters: dict,
    df_filtered: Any,
    forecast_mensual: float = 0.0,
    produccion_parcial: float = 0.0,
    presupuesto_mensual: float = 0.0,
    acumulado_anio: float = 0.0,
    presupuesto_anual: float = 0.0,
    dias_transcurridos: int = 0,
    dias_totales: int = 0,
) -> str:
    """Construye el prompt del sistema con contexto del dashboard.

    Args:
        fecha_corte: Timestamp de la fecha de corte actual.
        filters: Diccionario con filtros aplicados (linea_plus, ajuste_pct, etc.).
        df_filtered: DataFrame filtrado para obtener metadatos de sucursales y líneas.
        forecast_mensual: Forecast del mes actual.
        produccion_parcial: Producción acumulada hasta fecha de corte.
        presupuesto_mensual: Presupuesto del mes actual.
        acumulado_anio: Producción acumulada del año (YTD).
        presupuesto_anual: Presupuesto total del año.
        dias_transcurridos: Días hábiles transcurridos en el mes.
        dias_totales: Días hábiles totales del mes.

    Returns:
        Prompt del sistema listo para enviar a Groq.
    """
    linea_negocio = filters.get('linea_plus', 'TODAS')

    # Información de sucursales disponibles
    if 'SUCURSAL' in df_filtered.columns:
        sucursales = df_filtered['SUCURSAL'].dropna().unique().tolist()
        if len(sucursales) > 8:
            sucursales_info = f"{len(sucursales)} sucursales ({', '.join(sucursales[:5])}...)"
        elif sucursales:
            sucursales_info = ', '.join(sucursales)
        else:
            sucursales_info = "No filtradas"
    else:
        sucursales_info = "No disponible"

    # Líneas disponibles en los datos filtrados
    if 'LINEA_PLUS' in df_filtered.columns:
        lineas = sorted(df_filtered['LINEA_PLUS'].dropna().unique().tolist())
        lineas_disponibles = ', '.join(lineas) if lineas else 'No disponibles'
    else:
        lineas_disponibles = 'No disponibles'

    avance_mes_pct = (produccion_parcial / presupuesto_mensual * 100) if presupuesto_mensual > 0 else 0.0
    avance_anual_pct = (acumulado_anio / presupuesto_anual * 100) if presupuesto_anual > 0 else 0.0

    return SYSTEM_PROMPT_TEMPLATE.format(
        fecha_corte=fecha_corte.strftime('%d/%m/%Y') if hasattr(fecha_corte, 'strftime') else str(fecha_corte),
        linea_negocio=linea_negocio,
        forecast_mensual=forecast_mensual,
        produccion_parcial=produccion_parcial,
        dias_transcurridos=dias_transcurridos,
        dias_totales=dias_totales,
        presupuesto_mensual=presupuesto_mensual,
        avance_mes_pct=avance_mes_pct,
        acumulado_anio=acumulado_anio,
        presupuesto_anual=presupuesto_anual,
        avance_anual_pct=avance_anual_pct,
        sucursales_info=sucursales_info,
        lineas_disponibles=lineas_disponibles,
        ajuste_conservador=filters.get('ajuste_pct', 0.0),
    )


def get_ai_response(user_message: str, system_prompt: str, chat_history: list) -> str:
    """Obtiene respuesta de Groq (Llama 3.1 8B Instant).

    Args:
        user_message: Mensaje del usuario.
        system_prompt: Prompt del sistema con contexto del dashboard.
        chat_history: Historial de mensajes previos [{"role": ..., "content": ...}].

    Returns:
        Respuesta de la IA como string. Retorna mensaje de error si falla.
    """
    try:
        from groq import Groq
    except ImportError:
        return (
            "⚠️ **La librería `groq` no está instalada.**\n\n"
            "Ejecuta `pip install groq` y reinicia la aplicación."
        )

    api_key = st.secrets.get("GROQ_API_KEY", "")
    if not api_key:
        return (
            "⚠️ **GROQ_API_KEY no configurada.**\n\n"
            "Agrega tu API key en `.streamlit/secrets.toml`:\n"
            "```toml\nGROQ_API_KEY = \"gsk_...\"\n```"
        )

    try:
        client = Groq(api_key=api_key)

        messages = [{"role": "system", "content": system_prompt}]

        # Incluir historial (máximo últimos 10 turnos para no exceder contexto)
        for msg in chat_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=512,
            temperature=0.7,
        )
        return response.choices[0].message.content

    except Exception as exc:
        return f"⚠️ **Error al conectar con Groq:** {exc}"

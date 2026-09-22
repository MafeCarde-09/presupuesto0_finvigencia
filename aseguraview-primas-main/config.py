# -*- coding: utf-8 -*-
"""
Configuración centralizada para AseguraView
"""
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

# ==================== GOOGLE SHEETS ====================
SHEET_ID = os.getenv(
    'GOOGLE_SHEET_ID', 
    '1ThVwW3IbkL7Dw_Vrs9heT1QMiHDZw1Aj-n0XNbDi9i8'
)
SHEET_NAME_DATOS = os.getenv('SHEET_NAME_DATOS', 'Hoja1')
SHEET_NAME_FECHA_CORTE = os.getenv('SHEET_NAME_FECHA', 'Hoja2')

# ==================== FORMATO DE FECHAS ====================
DATE_FORMAT = '%d/%m/%Y'  # Formato colombiano: 1/1/2007
DATE_PARSE_DAYFIRST = True

# ==================== LEY DE GARANTÍAS 2026 ====================
LEY_GARANTIAS_2026 = {
    'inicio': os.getenv('FIANZAS_LEY_GARANTIAS_INICIO', '2026-01-31'),
    'fin_primera_vuelta': os.getenv('FIANZAS_LEY_GARANTIAS_FIN_1V', '2026-05-24'),
    'fin_segunda_vuelta': os.getenv('FIANZAS_LEY_GARANTIAS_FIN_2V', '2026-06-21'),
    'usar_segunda_vuelta': os.getenv('FIANZAS_USAR_SEGUNDA_VUELTA', 'True').lower() == 'true',
}

# Factores de ajuste por fase
ADJUSTMENT_FACTORS = {
    'pre_garantias': {
        'meses_antes': 2,  # Nov-Dic 2025
        'factor': float(os.getenv('FIANZAS_FACTOR_PRE', '0.75')),
        'descripcion': 'Pre-electoral: empresas adelantan licitaciones'
    },
    'garantias_activa': {
        'factor': float(os.getenv('FIANZAS_FACTOR_DURANTE', '0.25')),
        'descripcion': 'Ley activa: restricción fuerte en licitaciones públicas'
    },
    'post_garantias': {
        'meses_despues': 2,  # Jul-Ago 2026
        'factor': float(os.getenv('FIANZAS_FACTOR_POST', '0.60')),
        'descripcion': 'Post-ley: recuperación gradual'
    },
    'recuperacion': {
        'meses_despues': 3,  # Sep-Nov 2026
        'factor': float(os.getenv('FIANZAS_FACTOR_REBOTE', '1.10')),
        'descripcion': 'Recuperación: efecto rebote (licitaciones represadas)'
    }
}

# Ramos afectados por Ley de Garantías
RAMOS_FIANZAS_AFECTADOS = [
    'FIANZAS CUMPLIMIENTO',
    'FIANZAS SERIEDAD OFERTA',
    'FIANZAS ANTICIPO',
    'FIANZAS SALARIOS',
    'FIANZAS BUEN MANEJO',
    'FIANZAS GARANTIA'
]

# ==================== LÍNEAS DE NEGOCIO ====================
LINEAS_PRINCIPALES = [
    'SOAT',
    'FIANZAS',
    'VIDA',
    'AUTOS',
    'HOGAR',
    'PYMES',
    'SALUD',
    'ACCIDENTES',
    'RESPONSABILIDAD CIVIL',
    'TRANSPORTE'
]

# ==================== STREAMLIT CONFIG ====================
PAGE_TITLE = "AseguraView · Primas & Presupuesto"
PAGE_ICON = "📊"
LAYOUT = "wide"

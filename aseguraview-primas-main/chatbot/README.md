# 🤖 Chatbot IA — AseguraView

Módulo de chatbot inteligente integrado en AseguraView usando **Groq** (Llama 3.1 8B Instant).

## 📁 Estructura

```
chatbot/
├── __init__.py       # Exportaciones del módulo
├── chat_ui.py        # Componente UI: botón flotante + panel de chat
├── chat_logic.py     # Integración con Groq y construcción de contexto
├── prompts.py        # Templates de prompts del sistema
└── README.md         # Esta documentación
```

## 🚀 Uso

El chatbot se integra en `app.py` de la siguiente manera:

```python
from chatbot import render_chat_button, render_chat_panel, build_context

# 1. Inyectar CSS del botón flotante (al inicio de la app)
render_chat_button()

# 2. Construir contexto del dashboard
system_prompt = build_context(
    fecha_corte=fecha_corte,
    filters=filters,
    df_filtered=df_filtered,
    forecast_mensual=forecast_mensual,
    produccion_parcial=produccion_parcial,
    presupuesto_mensual=presupuesto_mensual,
    acumulado_anio=acumulado_anio,
    presupuesto_anual=presupuesto_anual,
    dias_transcurridos=dias_transcurridos,
    dias_totales=dias_totales,
)

# 3. Renderizar el panel de chat
render_chat_panel(system_prompt)
```

## ⚙️ Configuración

### API Key de Groq

Agrega tu API key en `.streamlit/secrets.toml`:

```toml
GROQ_API_KEY = "gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

Obtén tu API key gratis en [console.groq.com](https://console.groq.com).

### Dependencias

```
groq>=0.4.0
```

## 🎨 Características

- **Botón flotante** estilo WhatsApp con animación de pulso (esquina inferior derecha)
- **Panel de chat** que se abre desde el sidebar de Streamlit
- **Contexto del dashboard**: fecha de corte, línea seleccionada, pronóstico, presupuesto
- **Preguntas sugeridas** al inicio de la conversación
- **Historial persistente** en `st.session_state`
- **Modelo**: Llama 3.1 8B Instant (respuestas en <3 segundos)
- **Respuestas en español** con formato Markdown y emojis

## 💬 Ejemplos de preguntas

- *"¿Cómo vamos vs presupuesto este mes?"*
- *"¿Qué línea tiene mejor rendimiento?"*
- *"¿Vamos a cumplir el presupuesto anual?"*
- *"¿Qué sucursales necesitan más seguimiento?"*
- *"Explícame el pronóstico del mes actual"*
- *"¿Cuál es el riesgo de no cumplir la meta?"*

## 🔒 Seguridad

- La API key **nunca** se incluye en el código fuente
- Se usa `st.secrets` para manejar credenciales de forma segura
- El historial de conversación solo persiste en la sesión del usuario (no se guarda en disco)

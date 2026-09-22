# -*- coding: utf-8 -*-
"""
Componente de UI del chatbot para AseguraView
Botón flotante estilo WhatsApp + Panel lateral deslizable
"""
import streamlit as st

from .prompts import SUGGESTED_QUESTIONS, WELCOME_MESSAGE
from .chat_logic import get_ai_response


# ─── CSS del chatbot ──────────────────────────────────────────────────────────
_CHAT_CSS = """
<style>
/* ── Botón flotante FAB ── */
.chat-fab-container {
    position: fixed;
    bottom: 28px;
    right: 28px;
    z-index: 9999;
}
.chat-fab {
    width: 62px;
    height: 62px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.5);
    animation: fabPulse 2.5s infinite;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
    font-size: 28px;
    line-height: 1;
    user-select: none;
    border: 2px solid rgba(255,255,255,0.25);
}
.chat-fab:hover {
    transform: scale(1.12);
    box-shadow: 0 6px 32px rgba(102, 126, 234, 0.75);
}
@keyframes fabPulse {
    0%, 100% { box-shadow: 0 4px 20px rgba(102,126,234,0.5); }
    50%       { box-shadow: 0 4px 36px rgba(118,75,162,0.75); }
}
.chat-fab-badge {
    position: absolute;
    top: -4px;
    right: -4px;
    width: 18px;
    height: 18px;
    background: #ef4444;
    border-radius: 50%;
    border: 2px solid #071428;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
}

/* ── Panel lateral ── */
.chat-panel-overlay {
    position: fixed;
    inset: 0;
    background: rgba(7,20,40,0.55);
    backdrop-filter: blur(3px);
    z-index: 9998;
}
.chat-panel {
    position: fixed;
    top: 0;
    right: 0;
    height: 100vh;
    width: 420px;
    max-width: 100vw;
    background: #0d1f3c;
    border-left: 1px solid rgba(102,126,234,0.3);
    box-shadow: -6px 0 40px rgba(0,0,0,0.4);
    display: flex;
    flex-direction: column;
    z-index: 9999;
    animation: slideInRight 0.3s cubic-bezier(0.16,1,0.3,1);
}
@keyframes slideInRight {
    from { transform: translateX(100%); opacity: 0; }
    to   { transform: translateX(0);    opacity: 1; }
}
@media (max-width: 480px) {
    .chat-panel { width: 100vw; }
}

/* ── Header del panel ── */
.chat-header {
    padding: 16px 20px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
}
.chat-header-title {
    font-size: 16px;
    font-weight: 700;
    color: #fff;
    margin: 0;
}
.chat-header-subtitle {
    font-size: 11px;
    color: rgba(255,255,255,0.8);
    margin: 0;
}

/* ── Mensajes ── */
.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    scroll-behavior: smooth;
}
.chat-msg-user {
    align-self: flex-end;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: #fff;
    border-radius: 18px 18px 4px 18px;
    padding: 10px 14px;
    max-width: 80%;
    font-size: 14px;
    line-height: 1.5;
}
.chat-msg-ai {
    align-self: flex-start;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.08);
    color: #e2e8f0;
    border-radius: 4px 18px 18px 18px;
    padding: 10px 14px;
    max-width: 85%;
    font-size: 14px;
    line-height: 1.6;
}
.chat-msg-ai-avatar {
    font-size: 18px;
    margin-bottom: 4px;
    display: block;
}
.chat-typing {
    align-self: flex-start;
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.08);
    color: #9fb7cc;
    border-radius: 4px 18px 18px 18px;
    padding: 10px 16px;
    font-size: 13px;
    font-style: italic;
    animation: typingPulse 1.2s ease-in-out infinite;
}
@keyframes typingPulse {
    0%,100% { opacity: 0.5; }
    50%      { opacity: 1;   }
}

/* ── Preguntas sugeridas ── */
.chat-suggestions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px 16px 4px;
    flex-shrink: 0;
    border-top: 1px solid rgba(255,255,255,0.06);
}
.chat-suggestion-label {
    font-size: 11px;
    color: #9fb7cc;
    width: 100%;
    margin-bottom: 4px;
}

/* ── Área de entrada ── */
.chat-input-area {
    padding: 12px 16px 16px;
    border-top: 1px solid rgba(255,255,255,0.08);
    flex-shrink: 0;
}
</style>
"""


def render_chat_button() -> None:
    """Inyecta el CSS del chatbot en el DOM de Streamlit."""
    st.markdown(_CHAT_CSS, unsafe_allow_html=True)


def _init_session_state() -> None:
    """Inicializa variables de session_state necesarias para el chat."""
    if 'chat_open' not in st.session_state:
        st.session_state.chat_open = False
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'chat_input_value' not in st.session_state:
        st.session_state.chat_input_value = ""


def render_chat_toggle_button() -> None:
    """Renderiza SOLO el botón de toggle del chatbot en el sidebar (sin computación pesada).

    Este botón es ligero y se renderiza siempre. El panel completo solo se carga
    cuando el usuario hace clic y st.session_state.chat_open == True.
    """
    _init_session_state()

    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🤖 Asistente IA")

        if st.session_state.chat_open:
            if st.button("🔽 Cerrar chat IA", key="close_chat_btn", use_container_width=True):
                st.session_state.chat_open = False
                st.rerun()
        else:
            if st.button("💬 Abrir chat IA", key="open_chat_btn", use_container_width=True):
                st.session_state.chat_open = True
                st.rerun()


def render_chat_panel(system_prompt: str) -> None:
    """Renderiza el panel completo del chatbot (asume que ya está abierto).

    Esta función NO renderiza el botón de toggle — eso lo hace
    render_chat_toggle_button() de forma independiente.

    Args:
        system_prompt: Prompt del sistema con contexto del dashboard,
                       generado por `chatbot.chat_logic.build_context`.
    """
    _init_session_state()

    # ── Panel de chat ──────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="chat-panel">
          <div class="chat-header">
            <div>
              <p class="chat-header-title">🤖 Asistente IA — AseguraView</p>
              <p class="chat-header-subtitle">Powered by Groq · Llama 3.1 8B Instant</p>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Historial de mensajes ──────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### 🤖 Asistente IA — AseguraView")

    # Mensaje de bienvenida si no hay historial
    if not st.session_state.chat_history:
        st.info(WELCOME_MESSAGE)

    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(msg["content"])

    # ── Preguntas sugeridas (solo si no hay historial) ─────────────────────
    if not st.session_state.chat_history:
        st.markdown("**💡 Preguntas sugeridas:**")
        cols = st.columns(2)
        for i, question in enumerate(SUGGESTED_QUESTIONS):
            with cols[i % 2]:
                if st.button(question, key=f"suggest_{i}", use_container_width=True):
                    _send_message(question, system_prompt)
                    st.rerun()

    # ── Input del usuario ──────────────────────────────────────────────────
    user_input = st.chat_input(
        "Pregúntame sobre tus datos de seguros...",
        key="chat_input_field",
    )

    if user_input and user_input.strip():
        _send_message(user_input.strip(), system_prompt)
        st.rerun()

    # ── Botón limpiar historial ────────────────────────────────────────────
    if st.session_state.chat_history:
        if st.button("🗑️ Limpiar conversación", key="clear_chat", use_container_width=True):
            st.session_state.chat_history = []
            st.rerun()


def _send_message(user_message: str, system_prompt: str) -> None:
    """Agrega el mensaje del usuario al historial y obtiene respuesta de la IA.

    Args:
        user_message: Texto del usuario.
        system_prompt: Prompt del sistema con contexto del dashboard.
    """
    st.session_state.chat_history.append({"role": "user", "content": user_message})

    with st.spinner("🤖 Pensando..."):
        ai_response = get_ai_response(
            user_message=user_message,
            system_prompt=system_prompt,
            # Pass history without the user message just appended, as it is sent separately
            chat_history=st.session_state.chat_history[:-1],
        )

    st.session_state.chat_history.append({"role": "assistant", "content": ai_response})

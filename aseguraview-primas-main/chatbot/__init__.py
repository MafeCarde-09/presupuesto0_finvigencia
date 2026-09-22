# -*- coding: utf-8 -*-
"""
Chatbot IA para AseguraView
Módulo de integración con Groq (Llama 3.1 8B Instant)
"""
from .chat_ui import render_chat_button, render_chat_panel, render_chat_toggle_button
from .chat_logic import get_ai_response, build_context

__all__ = [
    'render_chat_button',
    'render_chat_panel',
    'render_chat_toggle_button',
    'get_ai_response',
    'build_context',
]

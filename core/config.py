import os
from pathlib import Path

def _streamlit_secret(name, default=""):
    try:
        import streamlit as st
        return st.secrets.get(name, default)
    except Exception:
        return default

def get_secret(name, default=""):
    return _streamlit_secret(name, os.getenv(name, default))

def has_openai():
    return bool(get_secret("OPENAI_API_KEY"))

def has_supabase():
    return bool(
        get_secret("SUPABASE_URL")
        and (get_secret("SUPABASE_SECRET_KEY") or get_secret("SUPABASE_SERVICE_ROLE_KEY"))
    )

def app_password():
    return get_secret("APP_PASSWORD", "")

def openai_model():
    return get_secret("OPENAI_MODEL", "gpt-5")

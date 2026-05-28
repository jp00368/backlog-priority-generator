"""
Configuration loader.

Priority order:
  1. st.secrets  (Streamlit Community Cloud / local secrets.toml)
  2. Environment variables / .env file
  3. Empty strings (user fills in via sidebar)
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed; env vars still work

def _secret(key: str, default: str = "") -> str:
    """Read from st.secrets if available, fall back to env var."""
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, default))
    except Exception:
        return os.getenv(key, default)


def get_config() -> dict:
    return {
        "jira_url":             _secret("JIRA_URL"),
        "jira_email":           _secret("JIRA_EMAIL"),
        "jira_api_token":       _secret("JIRA_API_TOKEN"),
        "jira_project_key":     _secret("JIRA_PROJECT_KEY"),
        "tracking_field_id":    _secret("JIRA_TRACKING_FIELD_ID"),
        "tracking_field_name":  _secret("JIRA_TRACKING_FIELD_NAME", "Tracking ID"),
        "external_id_field_id": _secret("JIRA_EXTERNAL_ID_FIELD_ID"),
    }

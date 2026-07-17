"""
app_secrets.py

Reads the Helmholtz Blablador API key (used for AI summaries) from the
BLABLADOR_API_KEY environment variable. The key is never hardcoded here.
"""

import os

BLABLADOR_API_KEY = os.environ.get("BLABLADOR_API_KEY")

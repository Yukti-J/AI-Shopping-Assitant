"""
Test isolation. Env vars beat the .env file in pydantic-settings, so setting
them here (before any app module reads settings) guarantees:
  - tests never use your real API keys (no accidental live calls / quota use),
  - the retailer list is the documented default regardless of your .env.
"""
import os

os.environ["GEMINI_API_KEY"] = ""
os.environ["SERPAPI_API_KEY"] = ""
os.environ["TARGET_RETAILERS"] = "amazon.in,myntra.com,flipkart.com,ajio.com,meesho.com"

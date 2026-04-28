"""
Turkish Super League Discord Bot Configuration
"""

# Prefer environment variables for secrets
import os

def _load_dotenv(path: str = ".env") -> None:
    """
    Tiny .env loader (no dependencies).
    - Only sets keys that are not already in the environment.
    - Supports lines like KEY=value and quoted values KEY="value".
    """
    try:
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key:
                    os.environ[key] = val
    except Exception:
        # Never crash config import due to .env parsing.
        return

_load_dotenv()

# Discord Bot Token (get from https://discord.com/developers/applications)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# AI Model for match simulation (Gemini is now the primary engine)
# GROQ MODEL WAS: "llama-3.1-8b-instant" (REMOVED)

# --- YAPAY ZEKA MODELLERİ (AI MODELS) ---

INTERVIEW_MODEL = "gemini-3.1-flash-lite-preview" 

# ANA YAPAY ZEKA MODELLERİ
GEMINI_MODEL = "gemini-3.1-flash-lite-preview" 
# OpenRouter fallback models (tried in order).
# 1) Prefer a long-context free Qwen model for huge match prompts.
# 2) Fall back to OpenRouter's free router (auto-picks any available free model).
OPENROUTER_MODELS = [
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "qwen/qwen3-coder:free",
    "openrouter/free",
    "deepseek/deepseek-chat",
    "meta-llama/llama-3.3-70b-instruct",
]

# Faster OpenRouter chain for short prompts (transfer/interview/media).
# Put the free router first to avoid hitting a single provider's 429 repeatedly.
OPENROUTER_MODELS_FAST = [
    "qwen/qwen3-coder:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "openrouter/free",
    "mistralai/pixtral-12b:free",
    "microsoft/phi-3-mini-128k-instruct:free"
]

# API ANAHTARLARI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") 
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "") # Lütfen OpenRouter API Key'inizi buraya girin!

# If False: Gemini -> Groq only (no OpenRouter tier).
USE_OPENROUTER_FALLBACK = False

# Groq fallback (OpenAI-compatible)
# Set `GROQ_API_KEY` in your environment for safety.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192"
]
GROQ_MODEL = GROQ_MODELS[0]
# Local Fallback Settings
PREFER_LOCAL_FALLBACK = False # Use high-detail local algorithmic engine instead of Groq/OR fallback
AI_MAX_ATTEMPTS = 10
# Groq on-demand TPM limit is tight; keep fallback prompts under this estimate.
GROQ_MAX_REQUEST_TOKENS_EST = 6000
# Also cap Groq output tokens to avoid TPM "Requested" bursts.
GROQ_MAX_OUTPUT_TOKENS = 1800


# Command prefix
COMMAND_PREFIX = "!"

# Bot settings
SETTINGS = {
    "default_home_advantage": 0.12,  # 12% boost for home team
    "derby_variance": 0.25,  # Extra randomness in derbies
    "min_goals": 0,
    "max_goals_normal": 6,  # Normal match max goals
    "max_goals_high": 9,    # High scoring match max
    "card_probability": 0.15,  # Chance of card per match
    "injury_probability": 0.05,  # Chance of injury per match
    "penalty_probability": 0.08,  # Chance of penalty per match
}

# Turkish Super League teams for reference
TURKISH_TEAMS = [
    "Galatasaray", "Fenerbahçe", "Beşiktaş", "Trabzonspor",
    "Başakşehir", "Alanyaspor", "Konyaspor", "Kayserispor", 
    "Gaziantep FK", "Samsunspor", "Göztepe", "Kasımpaşa", 
    "Kocaelispor", "Amedspor", "Erzurumspor", "Erokspor", 
    "Eyüpspor", "Sakaryaspor"
]

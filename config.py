import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

BOLE_SKILL_REPO = os.environ.get(
    "BOLE_SKILL_REPO",
    "https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master",
)
BOLE_SKILL_DATA_URL = f"{BOLE_SKILL_REPO}/data/latest-24h.json"

TTS_ENGINE = str(os.environ.get("TTS_ENGINE", "edge-tts"))
SAY_VOICE = str(os.environ.get("SAY_VOICE", "zh-CN-XiaochenNeural"))
SAY_RATE = str(os.environ.get("SAY_RATE", "200"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TARGET_MINUTES = int(os.environ.get("TARGET_MINUTES", "30"))
AI_RELEVANCE_THRESHOLD = float(os.environ.get("AI_RELEVANCE_THRESHOLD", "0.3"))
MAX_NEWS_ITEMS = int(os.environ.get("MAX_NEWS_ITEMS", "50"))

SCHEDULE_HOUR = int(os.environ.get("SCHEDULE_HOUR", "8"))
SCHEDULE_MINUTE = int(os.environ.get("SCHEDULE_MINUTE", "0"))
SCHEDULE_CRON = f"{SCHEDULE_MINUTE} {SCHEDULE_HOUR} * * *"
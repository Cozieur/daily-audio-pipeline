import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

# ─── User config (JSON) ──────────────────────────────────
# 用户可配置项存储在 user_config.json，仪表盘读写此文件
# 如果文件不存在则使用下方默认值
_USER_CONFIG_FILE = ROOT / "user_config.json"

_DEFAULTS = {
    "TTS_ENGINE": "edge-tts",
    "SAY_VOICE": "zh-CN-XiaochenNeural",
    "SAY_RATE": "200",
    "TARGET_MINUTES": "30",
    "AI_RELEVANCE_THRESHOLD": "0.3",
    "MAX_NEWS_ITEMS": "50",
    "SCHEDULE_HOUR": "8",
    "SCHEDULE_MINUTE": "0",
}


def _load_user_config() -> dict:
    """Load user overrides from JSON file."""
    try:
        if _USER_CONFIG_FILE.exists():
            return json.loads(_USER_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _get(key: str, cast=str):
    """Resolve a config value: env var > user_config.json > default."""
    _uc = _load_user_config()
    default = _DEFAULTS.get(key, "")
    raw = os.environ.get(key) or _uc.get(key) or default
    try:
        return cast(raw)
    except (ValueError, TypeError):
        return cast(default)


# ─── Exported config ──────────────────────────────────────
BOLE_SKILL_REPO = os.environ.get(
    "BOLE_SKILL_REPO",
    "https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master",
)
BOLE_SKILL_DATA_URL = f"{BOLE_SKILL_REPO}/data/latest-24h.json"

TTS_ENGINE = _get("TTS_ENGINE", str)
SAY_VOICE = _get("SAY_VOICE", str)
SAY_RATE = _get("SAY_RATE", str)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

TARGET_MINUTES = _get("TARGET_MINUTES", int)
AI_RELEVANCE_THRESHOLD = _get("AI_RELEVANCE_THRESHOLD", float)
MAX_NEWS_ITEMS = _get("MAX_NEWS_ITEMS", int)

SCHEDULE_HOUR = _get("SCHEDULE_HOUR", int)
SCHEDULE_MINUTE = _get("SCHEDULE_MINUTE", int)
SCHEDULE_CRON = f"{SCHEDULE_MINUTE} {SCHEDULE_HOUR} * * *"

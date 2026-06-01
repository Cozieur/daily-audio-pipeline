import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from adapters.base import ContentAdapter
from config import BOLE_SKILL_DATA_URL

logger = logging.getLogger("pipeline")

CACHE_FILE = Path(__file__).resolve().parent.parent / "output" / ".bole_cache.json"
CACHE_TTL = 3600  # 1 hour cache to avoid repeated slow downloads


class BoleSkillAdapter(ContentAdapter):
    def __init__(self, data_url: str = BOLE_SKILL_DATA_URL, use_ai_filtered: bool = True):
        self._data_url = data_url
        self._use_ai_filtered = use_ai_filtered

    def source_name(self) -> str:
        return "伯乐Skill AI News Radar"

    def fetch(self) -> list[dict]:
        data = self._fetch_json()
        items = self._extract_items(data)
        return [self._normalize(item) for item in items]

    def _http_get(self, url: str, timeout: int = 120) -> str:
        """Fetch URL content using stdlib urllib (replaces curl subprocess)."""
        req = urllib.request.Request(url, headers={"User-Agent": "DailyAudioPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _fetch_json(self) -> dict:
        # Try cache first
        cached = self._load_cache()
        if cached:
            return cached

        last_error = None
        for attempt in range(2):
            try:
                url = self._data_url
                if attempt == 1:
                    # cache-busting on retry
                    url = f"{self._data_url}?_={int(datetime.now().timestamp())}"
                raw = self._http_get(url)
                if not raw.strip():
                    last_error = "HTTP 返回空内容"
                    continue
                try:
                    data = json.loads(raw)
                    self._save_cache(data)
                    return data
                except json.JSONDecodeError as e:
                    last_error = f"JSON 解析失败（第{attempt+1}次）: {e}"
                    continue
            except urllib.error.URLError as e:
                last_error = f"第{attempt+1}次网络错误: {e}"
                continue
            except TimeoutError as e:
                last_error = f"第{attempt+1}次超时: {e}"
                continue
            except Exception as e:
                last_error = f"第{attempt+1}次异常: {e}"
                continue
        raise RuntimeError(f"获取伯乐Skill数据失败（已重试）: {last_error}")

    def _load_cache(self) -> dict | None:
        try:
            if CACHE_FILE.exists():
                age = datetime.now().timestamp() - CACHE_FILE.stat().st_mtime
                if age < CACHE_TTL:
                    data = json.loads(CACHE_FILE.read_text())
                    logger.info(f"📦 使用伯乐Skill缓存（{(age/60):.0f}分钟前）")
                    return data
            return None
        except Exception:
            return None

    def _save_cache(self, data: dict) -> None:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    def _extract_items(self, data: dict) -> list[dict]:
        if self._use_ai_filtered and "items_ai" in data and isinstance(data["items_ai"], list):
            return data["items_ai"]
        for key in ("items", "data", "news", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        raise RuntimeError(f"无法在返回数据中找到新闻列表，可用键: {list(data.keys())}")

    def _normalize(self, raw: dict) -> dict:
        title = (
            raw.get("title_zh")
            or raw.get("title")
            or raw.get("title_en")
            or ""
        )

        return {
            "title": title.strip(),
            "url": raw.get("url") or "",
            "summary": "",
            "source": raw.get("source") or raw.get("site_name") or raw.get("site_id") or "",
            "published_at": raw.get("published_at") or raw.get("first_seen_at") or "",
            "ai_relevance_score": raw.get("ai_score", 0) or 0,
            "ai_is_related": raw.get("ai_is_related", False),
            "title_en": (raw.get("title_en") or "").strip(),
        }


def test():
    adapter = BoleSkillAdapter()
    items = adapter.fetch()
    print(f"获取到 {len(items)} 条新闻")
    if items:
        print(f"\n字段示例:")
        for k, v in items[0].items():
            print(f"  {k}: {v}")
        print(f"\n前5条:")
        for item in items[:5]:
            score = item["ai_relevance_score"]
            print(f"  [分数:{score}] {item['title'][:60]}")


if __name__ == "__main__":
    test()

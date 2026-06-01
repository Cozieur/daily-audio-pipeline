#!/usr/bin/env python3
"""Daily Audio Pipeline - 每日语音内容推送管道的主编排器"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import (
    OUTPUT_DIR, TTS_ENGINE, TARGET_MINUTES, SAY_VOICE,
    AI_RELEVANCE_THRESHOLD, MAX_NEWS_ITEMS,
)
from adapters.bole_skill import BoleSkillAdapter
from adapters.horizon_adapter import HorizonAdapter
from engines.tts import create_tts_engine
from players.base import AirPlayPlayer

# ─── Logging setup ────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("pipeline")
logger.setLevel(logging.INFO)

# 文件 handler（带轮转，与 dashboard 共享同一个日志文件）
_file_handler = RotatingFileHandler(
    str(OUTPUT_DIR / "pipeline.log"),
    maxBytes=1024 * 1024, backupCount=3, encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_file_handler)

# 控制台 handler（同步输出到 stdout，供 dashboard 子进程捕获）
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_console_handler)

# ─── Cross-day dedup file ─────────────────────────────────
RECENT_TITLES_FILE = OUTPUT_DIR / ".recent_titles.json"
RECENT_DAYS = 3  # 保留最近 N 天的标题用于跨天去重


def _load_recent_titles() -> dict:
    """Load {date_str: [normalized_titles]} from disk."""
    try:
        if RECENT_TITLES_FILE.exists():
            data = json.loads(RECENT_TITLES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_recent_titles(data: dict) -> None:
    """Persist recent titles, pruning entries older than RECENT_DAYS."""
    today = datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in data.items() if k >= cutoff}
    try:
        RECENT_TITLES_FILE.write_text(
            json.dumps(pruned, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except Exception:
        pass


def _save_run_stats(stats: dict) -> None:
    """Append a structured run record to runs.jsonl (P3-13)."""
    stats_file = OUTPUT_DIR / "runs.jsonl"
    try:
        with open(stats_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(stats, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ─── Title normalization & dedup ──────────────────────────

def _normalize_title(title: str) -> str:
    t = re.sub(r"[\s\u3000\xa0]+", "", title)
    t = re.sub(r'[「」【】《》\u201c\u201d\u2018\u2019""''（）()\u30fb、，。！？：；—·–→←↑↓⇒⇔-]', "", t)
    return t.lower()


def deduplicate_items(items: list[dict]) -> list[dict]:
    seen_norms: list[str] = []
    result: list[dict] = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        norm = _normalize_title(title)
        is_dup = False
        for sn in seen_norms:
            if norm in sn or sn in norm:
                is_dup = True
                break
        if not is_dup:
            result.append(item)
            seen_norms.append(norm)
    return result


def filter_cross_day_duplicates(items: list[dict], recent_titles: dict) -> list[dict]:
    """Remove items whose normalized title appeared in recent days (P1-3)."""
    all_recent_norms = []
    for titles in recent_titles.values():
        all_recent_norms.extend(titles)

    result = []
    for item in items:
        norm = _normalize_title(item.get("title") or "")
        is_dup = False
        for rn in all_recent_norms:
            if norm in rn or rn in norm:
                is_dup = True
                break
        if not is_dup:
            result.append(item)
    return result


def filter_and_sort(items: list[dict]) -> list[dict]:
    filtered = []
    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue

        score = item.get("ai_relevance_score", 0)
        if isinstance(score, (int, float)) and score > 0:
            if score < AI_RELEVANCE_THRESHOLD:
                continue

        filtered.append(item)

    filtered.sort(
        key=lambda x: (
            float(x.get("ai_relevance_score", 0) or 0),
            x.get("published_at") or "",
        ),
        reverse=True,
    )
    return filtered[:MAX_NEWS_ITEMS]


# 中文 TTS 平均语速（字符/分钟），用于估算播报时长
CHARS_PER_MINUTE = 250


def _get_greeting() -> str:
    """根据当前小时返回时段问候语。"""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "早上好"
    elif 12 <= hour < 18:
        return "下午好"
    elif 18 <= hour < 24:
        return "晚上好"
    else:
        return "夜深了"


def build_script(items: list[dict], target_minutes: int = 0) -> str:
    today = datetime.now().strftime("%Y年%m月%d日")
    greeting = _get_greeting()
    lines = [f"{greeting}，今天是{today}。以下是今天的新闻摘要。\n"]

    max_chars = target_minutes * CHARS_PER_MINUTE if target_minutes > 0 else 0
    current_chars = len(lines[0]) + 30  # 预留结尾语长度
    included_count = 0

    for i, item in enumerate(items, 1):
        title = item.get("title_zh") or item["title"]
        summary = (item.get("summary_zh") or item.get("summary") or "").strip()
        background = (item.get("background") or "").strip()

        if summary:
            line = f"第{i}条。{title}。{summary}"
        else:
            line = f"第{i}条。{title}"

        if background and len(background) > 20:
            bg_short = background[:120]
            line += f"。相关背景：{bg_short}"

        # 如果设置了时长上限，检查是否超出
        if max_chars > 0 and (current_chars + len(line)) > max_chars and included_count > 0:
            logger.info(f"  ⏱️ 已达目标时长 {target_minutes} 分钟上限，截断至 {included_count} 条")
            break

        lines.append(line)
        current_chars += len(line)
        included_count += 1

    ending = f"\n以上是今天的全部{included_count}条新闻。祝你一天好心情！"
    lines.append(ending)
    return "\n".join(lines)


def run_pipeline(adapter, tts_engine, player):
    run_start = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d")

    logger.info("=" * 50)
    logger.info(f"Daily Audio Pipeline - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"来源: {adapter.source_name()}")
    logger.info("=" * 50)

    source_name = adapter.source_name()

    logger.info("\n[1/5] 获取内容...")
    try:
        items = adapter.fetch()
    except RuntimeError as e:
        logger.error(f"  ❌ 获取内容失败: {e}")
        _save_run_stats({
            "date": date_str, "success": False, "error": str(e),
            "source": source_name, "duration_seconds": round(time.time() - run_start, 1),
        })
        return False
    logger.info(f"  ✅ 获取到 {len(items)} 条原始新闻")
    raw_count = len(items)

    logger.info("\n[2/5] 去重...")
    items = deduplicate_items(items)
    logger.info(f"  ✅ 去重后剩余 {len(items)} 条")

    # P1-3: 跨天去重
    recent_titles = _load_recent_titles()
    before_cross = len(items)
    items = filter_cross_day_duplicates(items, recent_titles)
    if before_cross != len(items):
        logger.info(f"  ✅ 跨天去重: {before_cross} → {len(items)} 条（过滤 {before_cross - len(items)} 条近期已播）")

    logger.info("\n[3/5] 过滤与排序...")
    items = filter_and_sort(items)
    logger.info(f"  ✅ 保留 {len(items)} 条 AI 相关新闻")

    if not items:
        logger.warning("  ⚠️ 没有可朗读的新闻，跳过今日播报")
        _save_run_stats({
            "date": date_str, "success": True, "news_count": 0,
            "source": source_name, "duration_seconds": round(time.time() - run_start, 1),
        })
        return True

    logger.info("\n[4/5] 生成口播稿...")
    script = build_script(items, target_minutes=TARGET_MINUTES)
    preview = script[:200].replace("\n", " ")
    logger.info(f"  口播稿预览: {preview}...")
    logger.info(f"  总字数: {len(script)}")

    transcript_path = OUTPUT_DIR / f"daily_news_{date_str}.txt"
    transcript_path.write_text(script, encoding="utf-8")
    logger.info(f"  ✅ 文字稿已保存: {transcript_path}")

    logger.info(f"\n[5/5] 语音合成与播放...")
    output_path = OUTPUT_DIR / f"daily_news_{date_str}"

    try:
        audio_file = tts_engine.synthesize(script, output_path)
        logger.info(f"  ✅ 音频生成: {audio_file}")
    except Exception as e:
        logger.error(f"  ❌ TTS 合成失败: {e}")
        _save_run_stats({
            "date": date_str, "success": False, "news_count": len(items),
            "error": f"TTS失败: {e}", "source": source_name,
            "duration_seconds": round(time.time() - run_start, 1),
        })
        return False

    audio_size_kb = 0
    try:
        audio_size_kb = round(Path(audio_file).stat().st_size / 1024)
    except Exception:
        pass

    try:
        player.play(audio_file)
        logger.info(f"  ✅ 音频已播放")
        logger.info(f"  💾 音频文件保留: {audio_file}（3天后自动清理）")
    except Exception as e:
        logger.error(f"  ❌ 播放失败: {e}")
        logger.info(f"  音频文件已保存，可手动播放: {audio_file}")

    # P3-13: 保存执行统计
    duration = round(time.time() - run_start, 1)
    _save_run_stats({
        "date": date_str,
        "success": True,
        "news_count": len(items),
        "raw_count": raw_count,
        "script_chars": len(script),
        "source": source_name,
        "audio_size_kb": audio_size_kb,
        "duration_seconds": duration,
    })

    # P1-3: 保存本次播报的标题用于后续跨天去重
    today_titles = [_normalize_title(item.get("title") or "") for item in items]
    recent_titles[date_str] = today_titles
    _save_recent_titles(recent_titles)

    logger.info("\n" + "=" * 50)
    logger.info(f"管道执行完成！({len(items)} 条新闻, {duration}s)")
    logger.info("=" * 50)
    return True


def main():
    mode_file = Path(__file__).resolve().parent / "mode.json"
    try:
        mode = json.loads(mode_file.read_text()).get("mode", "horizon")
    except Exception:
        mode = "horizon"

    if mode == "bole":
        logger.info(f"⚙️ 使用伯乐Skill数据源（无 token 消耗）")
        adapter = BoleSkillAdapter()
    else:
        try:
            adapter = HorizonAdapter()
            if not adapter.ping():
                raise RuntimeError("Horizon 数据目录为空或未配置")
            logger.info(f"✅ 使用 Horizon 数据源（消耗 DeepSeek token）")
        except Exception as e:
            logger.warning(f"⚠️ Horizon 不可用（{e}），使用伯乐Skill数据源")
            adapter = BoleSkillAdapter()
    tts_engine = create_tts_engine(TTS_ENGINE, voice=SAY_VOICE)
    player = AirPlayPlayer(save_dir=OUTPUT_DIR)
    success = run_pipeline(adapter, tts_engine, player)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

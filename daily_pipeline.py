#!/usr/bin/env python3
"""Daily Audio Pipeline - 每日语音内容推送管道的主编排器"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from config import (
    OUTPUT_DIR, TTS_ENGINE, TARGET_MINUTES, SAY_VOICE,
    AI_RELEVANCE_THRESHOLD, MAX_NEWS_ITEMS,
)
from adapters.bole_skill import BoleSkillAdapter
from adapters.horizon_adapter import HorizonAdapter
from engines.tts import create_tts_engine
from players.base import AirPlayPlayer


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
            print(f"  ⏱️ 已达目标时长 {target_minutes} 分钟上限，截断至 {included_count} 条")
            break

        lines.append(line)
        current_chars += len(line)
        included_count += 1

    ending = f"\n以上是今天的全部{included_count}条新闻。祝你一天好心情！"
    lines.append(ending)
    return "\n".join(lines)


def run_pipeline(adapter, tts_engine, player):
    print("=" * 50)
    print(f"Daily Audio Pipeline - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"来源: {adapter.source_name()}")
    print("=" * 50)

    print("\n[1/5] 获取内容...")
    try:
        items = adapter.fetch()
    except RuntimeError as e:
        print(f"  ❌ 获取内容失败: {e}")
        return False
    print(f"  ✅ 获取到 {len(items)} 条原始新闻")

    print("\n[2/5] 去重...")
    items = deduplicate_items(items)
    print(f"  ✅ 去重后剩余 {len(items)} 条")

    print("\n[3/5] 过滤与排序...")
    items = filter_and_sort(items)
    print(f"  ✅ 保留 {len(items)} 条 AI 相关新闻")

    if not items:
        print("  ⚠️ 没有可朗读的新闻，跳过今日播报")
        return True

    print("\n[4/5] 生成口播稿...")
    script = build_script(items, target_minutes=TARGET_MINUTES)
    preview = script[:200].replace("\n", " ")
    print(f"  口播稿预览: {preview}...")
    print(f"  总字数: {len(script)}")

    date_str = datetime.now().strftime("%Y-%m-%d")

    transcript_path = OUTPUT_DIR / f"daily_news_{date_str}.txt"
    transcript_path.write_text(script, encoding="utf-8")
    print(f"  ✅ 文字稿已保存: {transcript_path}")

    print(f"\n[5/5] 语音合成与播放...")
    output_path = OUTPUT_DIR / f"daily_news_{date_str}"

    try:
        audio_file = tts_engine.synthesize(script, output_path)
        print(f"  ✅ 音频生成: {audio_file}")
    except Exception as e:
        print(f"  ❌ TTS 合成失败: {e}")
        return False

    try:
        player.play(audio_file)
        print(f"  ✅ 音频已播放")
        print(f"  💾 音频文件保留: {audio_file}（3天后自动清理）")
    except Exception as e:
        print(f"  ❌ 播放失败: {e}")
        print(f"  音频文件已保存，可手动播放: {audio_file}")

    print("\n" + "=" * 50)
    print("管道执行完成！")
    print("=" * 50)
    return True


def main():
    mode_file = Path(__file__).resolve().parent / "mode.json"
    try:
        mode = json.loads(mode_file.read_text()).get("mode", "horizon")
    except Exception:
        mode = "horizon"

    if mode == "bole":
        print(f"⚙️ 使用伯乐Skill数据源（无 token 消耗）")
        adapter = BoleSkillAdapter()
    else:
        try:
            adapter = HorizonAdapter()
            if not adapter.ping():
                raise RuntimeError("Horizon 数据目录为空或未配置")
            print(f"✅ 使用 Horizon 数据源（消耗 DeepSeek token）")
        except Exception as e:
            print(f"⚠️ Horizon 不可用（{e}），使用伯乐Skill数据源")
            adapter = BoleSkillAdapter()
    tts_engine = create_tts_engine(TTS_ENGINE, voice=SAY_VOICE)
    player = AirPlayPlayer(save_dir=OUTPUT_DIR)
    success = run_pipeline(adapter, tts_engine, player)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
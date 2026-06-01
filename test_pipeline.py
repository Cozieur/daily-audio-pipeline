#!/usr/bin/env python3
"""Daily Audio Pipeline - 基础单元测试"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))


class TestNormalizeTitle(unittest.TestCase):
    def test_removes_whitespace(self):
        from daily_pipeline import _normalize_title
        self.assertEqual(_normalize_title("hello  world"), "helloworld")
        self.assertEqual(_normalize_title("a\u3000b"), "ab")

    def test_removes_punctuation(self):
        from daily_pipeline import _normalize_title
        self.assertEqual(_normalize_title("「标题」"), "标题")
        self.assertEqual(_normalize_title("Hello-World"), "helloworld")

    def test_case_insensitive(self):
        from daily_pipeline import _normalize_title
        self.assertEqual(_normalize_title("ABC"), _normalize_title("abc"))


class TestDeduplicateItems(unittest.TestCase):
    def test_exact_duplicate(self):
        from daily_pipeline import deduplicate_items
        items = [
            {"title": "OpenAI 发布 GPT-5"},
            {"title": "OpenAI 发布 GPT-5"},
        ]
        result = deduplicate_items(items)
        self.assertEqual(len(result), 1)

    def test_substring_duplicate(self):
        from daily_pipeline import deduplicate_items
        items = [
            {"title": "OpenAI 发布 GPT-5 模型"},
            {"title": "OpenAI 发布 GPT-5"},
        ]
        result = deduplicate_items(items)
        self.assertEqual(len(result), 1)

    def test_different_titles(self):
        from daily_pipeline import deduplicate_items
        items = [
            {"title": "OpenAI 发布 GPT-5"},
            {"title": "Google 发布 Gemini 3"},
        ]
        result = deduplicate_items(items)
        self.assertEqual(len(result), 2)

    def test_empty_title_skipped(self):
        from daily_pipeline import deduplicate_items
        items = [{"title": ""}, {"title": "Valid"}]
        result = deduplicate_items(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Valid")


class TestFilterAndSort(unittest.TestCase):
    def test_filters_below_threshold(self):
        from daily_pipeline import filter_and_sort
        items = [
            {"title": "A", "ai_relevance_score": 0.1},
            {"title": "B", "ai_relevance_score": 0.8},
        ]
        with patch("daily_pipeline.AI_RELEVANCE_THRESHOLD", 0.3):
            with patch("daily_pipeline.MAX_NEWS_ITEMS", 50):
                result = filter_and_sort(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "B")

    def test_sorts_by_score_descending(self):
        from daily_pipeline import filter_and_sort
        items = [
            {"title": "Low", "ai_relevance_score": 0.4},
            {"title": "High", "ai_relevance_score": 0.9},
            {"title": "Mid", "ai_relevance_score": 0.6},
        ]
        with patch("daily_pipeline.AI_RELEVANCE_THRESHOLD", 0.3):
            with patch("daily_pipeline.MAX_NEWS_ITEMS", 50):
                result = filter_and_sort(items)
        self.assertEqual(result[0]["title"], "High")
        self.assertEqual(result[-1]["title"], "Low")

    def test_max_items_limit(self):
        from daily_pipeline import filter_and_sort
        items = [{"title": f"Item {i}", "ai_relevance_score": 0.5} for i in range(100)]
        with patch("daily_pipeline.AI_RELEVANCE_THRESHOLD", 0.3):
            with patch("daily_pipeline.MAX_NEWS_ITEMS", 10):
                result = filter_and_sort(items)
        self.assertEqual(len(result), 10)


class TestBuildScript(unittest.TestCase):
    def _make_items(self, n):
        return [{"title": f"新闻{i}", "title_zh": f"中文新闻{i}", "summary_zh": f"摘要{i}"} for i in range(1, n + 1)]

    def test_basic_output(self):
        from daily_pipeline import build_script
        items = self._make_items(3)
        script = build_script(items)
        self.assertIn("中文新闻1", script)
        self.assertIn("中文新闻3", script)
        self.assertIn("3条新闻", script)

    def test_target_minutes_truncation(self):
        from daily_pipeline import build_script
        items = self._make_items(50)
        # 1 分钟 = 250 字，应该会被截断
        script = build_script(items, target_minutes=1)
        # 截断后的新闻条数应该少于50条
        self.assertLess(script.count("第"), 50)
        self.assertIn("条新闻", script)

    def test_time_aware_greeting(self):
        from daily_pipeline import build_script, _get_greeting
        greeting = _get_greeting()
        self.assertIn(greeting, ["早上好", "下午好", "晚上好", "夜深了"])

    def test_empty_items(self):
        from daily_pipeline import build_script
        script = build_script([])
        self.assertIn("0条新闻", script)


class TestGetGreeting(unittest.TestCase):
    @patch("daily_pipeline.datetime")
    def test_morning(self, mock_dt):
        from daily_pipeline import _get_greeting
        mock_dt.now.return_value.hour = 8
        mock_dt.now.return_value.strftime = lambda f: "2026年06月01日"
        self.assertEqual(_get_greeting(), "早上好")

    @patch("daily_pipeline.datetime")
    def test_afternoon(self, mock_dt):
        from daily_pipeline import _get_greeting
        mock_dt.now.return_value.hour = 14
        self.assertEqual(_get_greeting(), "下午好")

    @patch("daily_pipeline.datetime")
    def test_evening(self, mock_dt):
        from daily_pipeline import _get_greeting
        mock_dt.now.return_value.hour = 20
        self.assertEqual(_get_greeting(), "晚上好")


class TestHorizonAdapterPing(unittest.TestCase):
    def test_ping_missing_directory(self):
        from adapters.horizon_adapter import HorizonAdapter
        adapter = HorizonAdapter(summary_dir="/nonexistent/path")
        self.assertFalse(adapter.ping())


class TestBoleSkillNormalize(unittest.TestCase):
    def test_normalize_title_zh(self):
        from adapters.bole_skill import BoleSkillAdapter
        adapter = BoleSkillAdapter()
        result = adapter._normalize({"title_zh": "中文标题", "title": "English"})
        self.assertEqual(result["title"], "中文标题")

    def test_normalize_fallback(self):
        from adapters.bole_skill import BoleSkillAdapter
        adapter = BoleSkillAdapter()
        result = adapter._normalize({"title": "English Only"})
        self.assertEqual(result["title"], "English Only")

    def test_normalize_empty(self):
        from adapters.bole_skill import BoleSkillAdapter
        adapter = BoleSkillAdapter()
        result = adapter._normalize({})
        self.assertEqual(result["title"], "")


class TestCreateTTSEngine(unittest.TestCase):
    def test_edge_tts_default_voice(self):
        from engines.tts import create_tts_engine, EdgeTTSEngine
        engine = create_tts_engine("edge-tts")
        self.assertIsInstance(engine, EdgeTTSEngine)
        self.assertEqual(engine._voice, "zh-CN-XiaoxiaoNeural")

    def test_edge_tts_custom_voice(self):
        from engines.tts import create_tts_engine, EdgeTTSEngine
        engine = create_tts_engine("edge-tts", voice="zh-CN-YunxiNeural")
        self.assertIsInstance(engine, EdgeTTSEngine)
        self.assertEqual(engine._voice, "zh-CN-YunxiNeural")

    def test_edge_tts_invalid_voice_fallback(self):
        from engines.tts import create_tts_engine, EdgeTTSEngine
        engine = create_tts_engine("edge-tts", voice="Tingting")
        self.assertIsInstance(engine, EdgeTTSEngine)
        self.assertEqual(engine._voice, "zh-CN-XiaoxiaoNeural")

    def test_say_engine_fallback(self):
        from engines.tts import create_tts_engine, SayTTSEngine
        engine = create_tts_engine("say")
        self.assertIsInstance(engine, SayTTSEngine)

    def test_unknown_engine_fallback(self):
        from engines.tts import create_tts_engine, SayTTSEngine
        engine = create_tts_engine("openai")
        self.assertIsInstance(engine, SayTTSEngine)


class TestDashboardDateValidation(unittest.TestCase):
    def test_valid_dates(self):
        from dashboard import _is_valid_date
        self.assertTrue(_is_valid_date("2026-06-01"))
        self.assertTrue(_is_valid_date("2025-12-31"))

    def test_path_traversal_rejected(self):
        from dashboard import _is_valid_date
        self.assertFalse(_is_valid_date("../../etc/passwd"))
        self.assertFalse(_is_valid_date("..\\..\\windows"))

    def test_invalid_formats_rejected(self):
        from dashboard import _is_valid_date
        self.assertFalse(_is_valid_date("2026/06/01"))
        self.assertFalse(_is_valid_date("06-01-2026"))
        self.assertFalse(_is_valid_date("abc"))
        self.assertFalse(_is_valid_date(""))
        self.assertFalse(_is_valid_date("2026-6-1"))


if __name__ == "__main__":
    unittest.main()

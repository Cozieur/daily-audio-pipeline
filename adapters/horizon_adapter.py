import re
from pathlib import Path
from datetime import datetime

from adapters.base import ContentAdapter


HORIZON_SUMMARY_DIR = Path(__file__).resolve().parent.parent.parent / "Horizon" / "data" / "summaries"


class HorizonAdapter(ContentAdapter):
    def __init__(self, lang: str = "zh", summary_dir: str | Path | None = None):
        self._lang = lang
        self._summary_dir = Path(summary_dir) if summary_dir else HORIZON_SUMMARY_DIR

    def source_name(self) -> str:
        return "Horizon · 多源 AI 新闻雷达"

    def ping(self) -> bool:
        """Check if Horizon summary directory has recent files, without fetching."""
        if not self._summary_dir.exists():
            return False
        pattern = f"horizon-*-{self._lang}.md"
        return bool(list(self._summary_dir.glob(pattern)))

    def fetch(self) -> list[dict]:
        latest = self._find_latest_summary()
        if not latest:
            raise RuntimeError(f"未找到 Horizon 日报文件（{self._summary_dir}）")
        text = latest.read_text(encoding="utf-8")
        return self._parse_summary(text)

    def _find_latest_summary(self) -> Path | None:
        pattern = f"horizon-*-{self._lang}.md"
        files = sorted(self._summary_dir.glob(pattern), reverse=True)
        if files:
            return files[0]
        return None

    def _parse_summary(self, text: str) -> list[dict]:
        items: list[dict] = []

        anchor_map: dict[str, str] = {}
        for m in re.finditer(r'^(\d+)\.\s+\[(.+?)\]\((#item-\d+)\)\s*(?:[⭐🌟]\ufe0f?)?\s*([\d.]+)/10', text, re.MULTILINE):
            num = int(m.group(1))
            title = m.group(2).strip()
            anchor = m.group(3)
            score = float(m.group(4))
            anchor_map[anchor] = title
            items.append({
                "title": title,
                "url": "",
                "summary": "",
                "source": "",
                "published_at": "",
                "ai_relevance_score": score / 10.0,
                "ai_is_related": score >= 6.0,
                "background": "",
                "tags": [],
                "num": num,
                "anchor": anchor,
            })

        detail_sections = re.split(r'^##\s+', text, flags=re.MULTILINE)
        for section in detail_sections[1:]:
            self._parse_detail_section(section, items)

        items.sort(key=lambda x: x.get("num", 999))
        return items

    def _parse_detail_section(self, section: str, items: list[dict]) -> None:
        lines = section.strip().split("\n")
        if not lines:
            return

        title_line = lines[0].strip()
        title_match = re.match(r'^\[(.+?)\]\((.+?)\)', title_line)
        if not title_match:
            title_text = title_line.strip()
        else:
            title_text = title_match.group(1).strip()

        body = "\n".join(lines[1:])

        url = ""
        if title_match:
            url = title_match.group(2).strip()

        source = ""
        source_line = re.search(
            r'^([\w\s/·@.\-]+?)\s*[·•●]\s*(.+?)\s*[·•●]\s*(.+?)$',
            body, re.MULTILINE
        )
        if source_line:
            source = source_line.group(1).strip()

        background = ""
        for kw in ("**Background**", "**背景**"):
            ctx_match = re.search(rf'{re.escape(kw)}\s*:\s*(.+?)(?:\n\n|\*\*标签|\*\*Tags|\*\*社区讨论|\*\*参考链接|<details|\Z)', body, re.DOTALL)
            if ctx_match:
                background = ctx_match.group(1).strip()
                break

        summary = ""
        summary_end = len(body)
        for kw in ("**Background**", "**背景**", "**社区讨论**", "**标签**", "**Tags**", "<details>"):
            idx = body.find(kw)
            if idx != -1 and idx < summary_end:
                summary_end = idx

        if source_line:
            source_start = body.find(source_line.group(0))
            if source_start != -1:
                summary = body[:source_start].strip()
            else:
                summary = body[:summary_end].strip()
        else:
            summary = body[:summary_end].strip()

        tags = []
        for kw in ("**Tags**", "**标签**"):
            tags_match = re.search(rf'{re.escape(kw)}\s*:\s*(.+?)$', body, re.DOTALL)
            if tags_match:
                raw_tags = tags_match.group(1).strip()
                tags = re.findall(r'#(\S+)', raw_tags)
                break

        for item in items:
            if item["title"] == title_text or item["title"] in title_text or title_text in item["title"]:
                item["url"] = url
                item["summary"] = summary[:300]
                item["source"] = source or "Horizon"
                item["background"] = background
                item["tags"] = tags
                break


def test():
    adapter = HorizonAdapter()
    try:
        items = adapter.fetch()
        print(f"获取到 {len(items)} 条新闻")
        for item in items[:5]:
            score = item["ai_relevance_score"]
            title = item["title"][:60]
            src = item["source"][:20] if item["source"] else "-"
            print(f"  [{score:.1f}] [{src}] {title}")
    except RuntimeError as e:
        print(f"⚠️ {e}")
        print("先运行 Horizon 再测试：")
        print("  cd ~/Documents/Horizon && uv run horizon")


if __name__ == "__main__":
    test()
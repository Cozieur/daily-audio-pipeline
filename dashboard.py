#!/usr/bin/env python3
"""Daily Audio Pipeline · 启动台 (Flask Dashboard)"""

import json
import logging
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, render_template

from engines.tts import create_tts_engine

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "config.py"
SOURCES_FILE = ROOT / "sources.json"
OUTPUT_DIR = ROOT / "output"
LOG_FILE = OUTPUT_DIR / "pipeline.log"
MODE_FILE = ROOT / "mode.json"
SCHEDULER_STATE_FILE = ROOT / "scheduler_state.json"
PLIST_FILE = ROOT / "com.daily-audio-pipeline.plist"
LAUNCH_DIR = Path.home() / "Library" / "LaunchAgents"

app = Flask(__name__)

# ─── Log rotation ────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = RotatingFileHandler(
    str(LOG_FILE), maxBytes=1024 * 1024, backupCount=3, encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger("pipeline").addHandler(_file_handler)
logging.getLogger("pipeline").setLevel(logging.INFO)
_pipeline_logger = logging.getLogger("pipeline")

# ─── Pipeline lock ────────────────────────────────────────
_pipeline_lock_obj = threading.Lock()
_pipeline_process: subprocess.Popen | None = None

# ─── Internal scheduler ──────────────────────────────────
_scheduler_enabled = False
_scheduler_hour = 8
_scheduler_minute = 40
_scheduler_thread: threading.Thread | None = None
_scheduler_stop = threading.Event()
_last_trigger_date: str | None = None  # YYYY-MM-DD of last trigger, prevents double-fire


def _load_scheduler_state() -> bool:
    """Load scheduler enabled/disabled from disk."""
    try:
        if SCHEDULER_STATE_FILE.exists():
            state = json.loads(SCHEDULER_STATE_FILE.read_text())
            return bool(state.get("enabled", False))
    except Exception:
        pass
    return False


def _save_scheduler_state() -> None:
    """Persist scheduler enabled/disabled to disk."""
    try:
        SCHEDULER_STATE_FILE.write_text(
            json.dumps({"enabled": _scheduler_enabled, "updated": datetime.now().isoformat()})
        )
    except Exception as e:
        print(f"⚠️ 调度器状态保存失败: {e}")


def _scheduler_loop():
    """Background loop: checks every 30s if it's time to run."""
    global _scheduler_enabled, _last_trigger_date
    while not _scheduler_stop.is_set():
        if _scheduler_enabled:
            now = datetime.now()
            cfg = parse_config()
            hour = int(cfg.get("SCHEDULE_HOUR", 8))
            minute = int(cfg.get("SCHEDULE_MINUTE", 0))
            today_str = now.strftime("%Y-%m-%d")
            # 匹配时间窗口（当前时间已过设定时间，且今天还没触发过）
            if (now.hour > hour or (now.hour == hour and now.minute >= minute)
                    and _last_trigger_date != today_str
                    and not _pipeline_lock_obj.locked()):
                print(f"⏰ 定时播报触发: {hour:02d}:{minute:02d}")
                _last_trigger_date = today_str
                try:
                    trigger_pipeline()
                except Exception as e:
                    print(f"⚠️ 定时播报执行失败: {e}")
        _scheduler_stop.wait(30)


def _ensure_scheduler():
    """Start the scheduler thread if not running."""
    global _scheduler_thread, _scheduler_enabled
    if _scheduler_thread is None or not _scheduler_thread.is_alive():
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
        _scheduler_thread.start()
        print("🕐 后台调度器已启动")
    # 从磁盘恢复调度器状态
    _scheduler_enabled = _load_scheduler_state()
    if _scheduler_enabled:
        print(f"📂 调度器状态已恢复: 运行中")


SHELL_LOCK_FILE = Path("/tmp/daily-audio-pipeline.lock")


def _shell_pipeline_running() -> bool:
    """Check if the shell script is already running (shared PID lock)."""
    try:
        if SHELL_LOCK_FILE.exists():
            pid = int(SHELL_LOCK_FILE.read_text().strip())
            # Check if process is still alive
            os.kill(pid, 0)
            return True
    except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
        pass
    return False


def _safe_release_lock():
    """Release the pipeline lock, ignoring if already released by another thread."""
    try:
        _pipeline_lock_obj.release()
    except RuntimeError:
        pass


def trigger_pipeline():
    """Run the pipeline in a background process (no lock check)."""
    global _pipeline_process
    # 检查 shell 脚本是否已经在跑（跨进程互斥）
    if _shell_pipeline_running():
        print("⚠️ Shell 管道已在运行，跳过本次触发")
        return
    script = str(ROOT / "run_daily.sh")
    _pipeline_lock_obj.acquire()
    try:
        proc = subprocess.Popen(
            ["bash", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        _pipeline_process = proc
    except Exception:
        _safe_release_lock()
        raise

    def _cleanup():
        global _pipeline_process
        # 将子进程输出写入日志文件（带轮转）
        try:
            for line in proc.stdout:
                _pipeline_logger.info(line.decode("utf-8", errors="replace").rstrip())
        except Exception:
            pass
        proc.wait()
        _pipeline_process = None
        _safe_release_lock()

    threading.Thread(target=_cleanup, daemon=True).start()

# ─── Source mode ──────────────────────────────────────────

def get_source_mode() -> str:
    try:
        return json.loads(MODE_FILE.read_text()).get("mode", "horizon")
    except Exception:
        return "horizon"


def set_source_mode(mode: str) -> None:
    MODE_FILE.write_text(json.dumps({"mode": mode}))


# ─── Sources storage ─────────────────────────────────────

DEFAULT_SOURCES = [
    {
        "id": "bole-skill",
        "name": "伯乐Skill · AI News Radar",
        "url": "https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master/data/latest-24h.json",
        "type": "json_api",
        "enabled": True,
    }
]


def load_sources():
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text())
    save_sources(DEFAULT_SOURCES)
    return DEFAULT_SOURCES


def save_sources(sources):
    SOURCES_FILE.write_text(json.dumps(sources, ensure_ascii=False, indent=2))


def next_id(sources):
    ids = [s["id"] for s in sources if s["id"].startswith("custom-")]
    nums = [int(s.split("-")[1]) for s in ids if s.split("-")[1].isdigit()]
    return f"custom-{(max(nums) + 1) if nums else 1}"


# ─── Config helpers ──────────────────────────────────────

USER_CONFIG_FILE = ROOT / "user_config.json"

_CONFIG_DEFAULTS = {
    "TTS_ENGINE": "edge-tts",
    "SAY_VOICE": "zh-CN-XiaoxiaoNeural",
    "SAY_RATE": "200",
    "TARGET_MINUTES": "30",
    "AI_RELEVANCE_THRESHOLD": "0.3",
    "MAX_NEWS_ITEMS": "50",
    "SCHEDULE_HOUR": "8",
    "SCHEDULE_MINUTE": "0",
}


def _load_user_config() -> dict:
    try:
        if USER_CONFIG_FILE.exists():
            return json.loads(USER_CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_user_config(data: dict) -> None:
    USER_CONFIG_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


def parse_config():
    uc = _load_user_config()
    cfg = {}
    for key, default in _CONFIG_DEFAULTS.items():
        cfg[key] = uc.get(key, default)
    return cfg


def write_config(key, value):
    if key not in _CONFIG_DEFAULTS:
        return False
    uc = _load_user_config()
    uc[key] = str(value)
    _save_user_config(uc)
    return True


def write_config_multi(updates):
    uc = _load_user_config()
    for key, value in updates.items():
        if key in _CONFIG_DEFAULTS:
            uc[key] = str(value)
    _save_user_config(uc)
    # Update env for current process
    for k in updates:
        if k in _CONFIG_DEFAULTS:
            os.environ[k] = str(uc[k])
    cfg = {}
    for key, default in _CONFIG_DEFAULTS.items():
        cfg[key] = uc.get(key, default)
    return cfg


# ─── Date validation ──────────────────────────────────

_VALID_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_date(date_str: str) -> bool:
    """Reject anything that is not a strict YYYY-MM-DD string."""
    return bool(_VALID_DATE_RE.match(date_str))


# ─── Transcript helpers ──────────────────────────────────

def list_transcripts():
    files = sorted(OUTPUT_DIR.glob("daily_news_*.txt"), reverse=True)
    result = []
    for f in files:
        date_str = f.stem.replace("daily_news_", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        lines = f.read_text(encoding="utf-8").strip().split("\n")
        news_count = sum(1 for l in lines if l.startswith("第"))
        # Check for audio file
        has_audio = False
        for ext in (".mp3", ".wav", ".aiff"):
            if (OUTPUT_DIR / f"daily_news_{date_str}{ext}").exists():
                has_audio = True
                break
        result.append({
            "date": date_str,
            "is_today": date_str == datetime.now().strftime("%Y-%m-%d"),
            "news_count": news_count,
            "size": f.stat().st_size,
            "has_audio": has_audio,
        })
    return result


def get_transcript(date_str):
    path = OUTPUT_DIR / f"daily_news_{date_str}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# ─── Log / status helpers ────────────────────────────────

def get_last_run():
    if not LOG_FILE.exists():
        return None
    text = LOG_FILE.read_text(encoding="utf-8")
    runs = [m for m in re.finditer(r"===== (.+?) =====", text)]
    if not runs:
        return None
    last = runs[-1]
    ts_str = last.group(1).strip()
    try:
        return datetime.strptime(ts_str, "%a %b %d %H:%M:%S %Z %Y").isoformat()
    except ValueError:
        return ts_str


def get_run_duration():
    if not LOG_FILE.exists():
        return None
    text = LOG_FILE.read_text(encoding="utf-8")
    # Look for content between last "=====" markers
    blocks = text.split("=====")
    if len(blocks) < 3:
        return None
    last = blocks[-1]
    m = re.search(r"(\d+) 条新闻", last)
    count = int(m.group(1)) if m else None
    return {"news_count": count}


# ─── API Routes ──────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    cfg = parse_config()
    transcripts = list_transcripts()
    last_run = get_last_run()
    run_info = get_run_duration()

    # Estimate next run
    now = datetime.now()
    next_run = now.replace(
        hour=int(cfg["SCHEDULE_HOUR"]),
        minute=int(cfg["SCHEDULE_MINUTE"]),
        second=0, microsecond=0,
    )
    if next_run <= now:
        next_run += timedelta(days=1)

    return jsonify({
        "last_run": last_run,
        "next_run": next_run.isoformat(),
        "next_run_display": next_run.strftime("%H:%M"),
        "is_today_done": transcripts and transcripts[0].get("is_today"),
        "is_playing": _pipeline_lock_obj.locked() or _shell_pipeline_running(),
        "source_mode": get_source_mode(),
        "run_info": run_info,
        "today": datetime.now().strftime("%Y-%m-%d"),
    })


@app.route("/api/transcripts")
def api_transcripts():
    return jsonify(list_transcripts())


@app.route("/api/transcript/<date>")
def api_transcript(date):
    if not _is_valid_date(date):
        return jsonify({"error": "invalid date format"}), 400
    text = get_transcript(date)
    if text is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"date": date, "text": text})


@app.route("/api/transcript/<date>/download")
def api_transcript_download(date):
    if not _is_valid_date(date):
        return jsonify({"error": "invalid date format"}), 400
    path = OUTPUT_DIR / f"daily_news_{date}.txt"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(OUTPUT_DIR), path.name, as_attachment=True)


@app.route("/api/audio/<date>")
def api_audio(date):
    """Serve historical audio file for a given date (P2-8)."""
    if not _is_valid_date(date):
        return jsonify({"error": "invalid date format"}), 400
    for ext in (".mp3", ".wav", ".aiff"):
        path = OUTPUT_DIR / f"daily_news_{date}{ext}"
        if path.exists():
            return send_from_directory(str(OUTPUT_DIR), path.name)
    return jsonify({"error": "audio not found"}), 404


@app.route("/api/audio/<date>/exists")
def api_audio_exists(date):
    """Check if an audio file exists for a given date (P2-8)."""
    if not _is_valid_date(date):
        return jsonify({"exists": False})
    for ext in (".mp3", ".wav", ".aiff"):
        path = OUTPUT_DIR / f"daily_news_{date}{ext}"
        if path.exists():
            return jsonify({"exists": True, "ext": ext})
    return jsonify({"exists": False})


@app.route("/api/test-voice", methods=["POST"])
def api_test_voice():
    """Synthesize a short test phrase and return audio stream (P2-9)."""
    data = request.get_json(force=True) or {}
    voice = data.get("voice", "zh-CN-XiaoxiaoNeural")
    engine_name = data.get("engine", "edge-tts")
    rate = data.get("rate", "200")
    test_text = "你好，这是语音试听测试。今天的天气真不错！"

    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="dap_test_")
    tmp_path = Path(tmp_dir) / "test_voice"

    try:
        engine = create_tts_engine(engine_name, voice=voice)
        audio_file = engine.synthesize(test_text, tmp_path)
        return send_from_directory(
            str(Path(audio_file).parent),
            Path(audio_file).name,
            mimetype="audio/mpeg" if audio_file.endswith(".mp3") else "audio/wav",
        )
    except Exception as e:
        return jsonify({"error": f"合成失败: {e}"}), 500


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(parse_config())
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "no data"}), 400
    cfg = write_config_multi(data)

    # 如果修改了播报时间，同步到 launchd 和内部调度器
    if "SCHEDULE_HOUR" in data or "SCHEDULE_MINUTE" in data:
        global _scheduler_hour, _scheduler_minute
        try:
            _scheduler_hour = int(cfg.get("SCHEDULE_HOUR", 8))
            _scheduler_minute = int(cfg.get("SCHEDULE_MINUTE", 0))
            _sync_launchd_time(_scheduler_hour, _scheduler_minute)
        except Exception as e:
            print(f"⚠️ launchd 时间同步失败: {e}")

    return jsonify({"ok": True, "config": cfg})


@app.route("/api/sources", methods=["GET"])
def api_sources_list():
    sources = load_sources()

    horizon_dir = ROOT.parent / "Horizon" / "data" / "summaries"
    horizon_ok = horizon_dir.exists() and bool(list(horizon_dir.glob("horizon-*.md")))

    sources.insert(0, {
        "id": "horizon",
        "name": "Horizon · 多源 AI 新闻雷达",
        "url": str(ROOT.parent / "Horizon"),
        "type": "local_ai_aggregator",
        "enabled": True,
        "builtin": True,
        "status": "可用" if horizon_ok else "未配置",
        "sources_detail": "Hacker News · RSS · Reddit · Telegram · GitHub · OSS Insight",
    })

    return jsonify(sources)


@app.route("/api/mode", methods=["GET"])
def api_mode_get():
    return jsonify({"mode": get_source_mode()})


@app.route("/api/mode", methods=["POST"])
def api_mode_set():
    data = request.get_json(force=True)
    mode = data.get("mode", "horizon")
    set_source_mode(mode)
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/sources", methods=["POST"])
def api_sources_add():
    sources = load_sources()
    data = request.get_json(force=True)
    new_source = {
        "id": next_id(sources),
        "name": data.get("name", ""),
        "url": data.get("url", ""),
        "type": data.get("type", "json_api"),
        "enabled": data.get("enabled", True),
    }
    sources.append(new_source)
    save_sources(sources)
    return jsonify({"ok": True, "source": new_source}), 201


@app.route("/api/sources/<source_id>", methods=["PUT", "DELETE"])
def api_source_ops(source_id):
    sources = load_sources()
    for s in sources:
        if s["id"] == source_id:
            if request.method == "DELETE":
                sources.remove(s)
                save_sources(sources)
                return jsonify({"ok": True})
            data = request.get_json(force=True)
            s.update(data)
            save_sources(sources)
            return jsonify({"ok": True, "source": s})
    return jsonify({"error": "not found"}), 404


@app.route("/api/play-now", methods=["POST"])
def api_play_now():
    if _pipeline_lock_obj.locked() or _shell_pipeline_running():
        return jsonify({"error": "pipeline 正在运行中，请等待完成或先停止"}), 409
    try:
        trigger_pipeline()
        return jsonify({"ok": True, "message": "播报已触发"})
    except Exception as e:
        _safe_release_lock()
        return jsonify({"error": str(e)}), 500


@app.route("/api/play-stop", methods=["POST"])
def api_play_stop():
    global _pipeline_process
    if not _pipeline_lock_obj.locked() or not _pipeline_process:
        return jsonify({"error": "没有正在运行的播报"}), 404
    pid = _pipeline_process.pid
    _pipeline_process = None
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    # _cleanup 线程会在进程退出后释放锁，这里不手动释放
    return jsonify({"ok": True, "message": "播报已停止"})


@app.route("/api/pipeline-log")
def api_pipeline_log():
    if not LOG_FILE.exists():
        return jsonify({"lines": []})
    text = LOG_FILE.read_text(encoding="utf-8")
    lines = text.strip().split("\n")
    tail = lines[-50:]
    return jsonify({"lines": tail, "total": len(lines)})


# ─── Schedule (internal + launchd) ───────────────────────

def _install_launch_plist():
    """Copy dashboard plist to LaunchAgents for auto-start on login."""
    dashboard_plist = ROOT / "com.dashboard.plist"
    target = LAUNCH_DIR / "com.daily-audio-pipeline.dashboard.plist"
    if not LAUNCH_DIR.exists():
        try:
            LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            return
    if not target.exists() and dashboard_plist.exists():
        try:
            shutil.copy2(str(dashboard_plist), str(target))
            print(f"📋 已安装仪表盘自启动 -> {target}")
        except (PermissionError, OSError):
            print(f"⚠️ 无法写入 {target}，请手动安装自启动")


def _sync_launchd_time(hour: int, minute: int):
    """Update the pipeline plist with new time (for manual terminal install)."""
    if not PLIST_FILE.exists():
        return
    with open(PLIST_FILE, "rb") as f:
        pl = plistlib.load(f)
    pl.setdefault("StartCalendarInterval", {})
    pl["StartCalendarInterval"]["Hour"] = hour
    pl["StartCalendarInterval"]["Minute"] = minute
    with open(PLIST_FILE, "wb") as f:
        plistlib.dump(pl, f)
    _install_launch_plist()


def _schedule_status() -> dict:
    """Return schedule status dict."""
    cfg = parse_config()
    hour = int(cfg["SCHEDULE_HOUR"])
    minute = int(cfg["SCHEDULE_MINUTE"])
    plist_installed = LAUNCH_DIR.exists() and (LAUNCH_DIR / "com.daily-audio-pipeline.dashboard.plist").exists()
    # 检查 launchd 中的仪表盘是否在运行
    dashboard_loaded = False
    try:
        r = subprocess.run(
            ["launchctl", "list", "com.daily-audio-pipeline.dashboard"],
            capture_output=True, text=True, timeout=5,
        )
        dashboard_loaded = r.returncode == 0
    except Exception:
        pass
    return {
        "loaded": _scheduler_enabled,
        "dashboard_loaded": dashboard_loaded,
        "plist_installed": plist_installed,
        "method": "internal",
        "hour": hour,
        "minute": minute,
    }


@app.route("/api/schedule", methods=["GET"])
def api_schedule_get():
    return jsonify(_schedule_status())


@app.route("/api/schedule", methods=["POST"])
def api_schedule_set():
    data = request.get_json(force=True) or {}
    action = data.get("action", "")
    global _scheduler_enabled

    if action == "pause":
        _scheduler_enabled = False
        _save_scheduler_state()
        print(f"⏸ 后台调度器已暂停（{datetime.now().strftime('%H:%M')}）")
        return jsonify({"ok": True, "message": "定时播报已暂停"})

    if action == "resume":
        _scheduler_enabled = True
        _save_scheduler_state()
        _ensure_scheduler()
        print(f"▶ 后台调度器已恢复（{datetime.now().strftime('%H:%M')}）")
        return jsonify({"ok": True, "message": "定时播报已恢复"})

    if action == "set_time":
        hour = data.get("hour")
        minute = data.get("minute")
        if hour is None or minute is None:
            return jsonify({"error": "请提供 hour 和 minute"}), 400
        try:
            hour = int(hour)
            minute = int(minute)
        except (ValueError, TypeError):
            return jsonify({"error": "hour/minute 必须为整数"}), 400
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return jsonify({"error": "时间范围无效"}), 400
        global _scheduler_hour, _scheduler_minute
        _scheduler_hour = hour
        _scheduler_minute = minute
        # 持久化到 user_config.json
        write_config_multi({"SCHEDULE_HOUR": str(hour), "SCHEDULE_MINUTE": str(minute)})
        # 同步到 plist（供终端手动安装用）
        try:
            _sync_launchd_time(hour, minute)
        except Exception:
            pass
        return jsonify({"ok": True, "message": f"播报时间已改为 {hour:02d}:{minute:02d}"})

    return jsonify({"error": f"未知操作: {action}"}), 400


# ─── Main ────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🎙️ Daily Audio Pipeline · 启动台")
    print(f"   打开 http://localhost:8765")
    print()

    # 首次启动：尝试安装自启动 plist
    _install_launch_plist()

    # 后台调度器默认关闭，由用户在界面中开启
    _ensure_scheduler()
    print(f"   定时播报: 暂停中（点击仪表盘「恢复」开启）")
    print()

    app.run(host="127.0.0.1", port=8765, debug=False)
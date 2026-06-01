#!/bin/bash
# Daily Audio Pipeline - 每日启动脚本
#
# 定时执行由 macOS launchd 管理（~/Library/LaunchAgents/com.daily-audio-pipeline.plist）
# 修改播报时间：编辑 config.py 中的 SCHEDULE_HOUR 和 SCHEDULE_MINUTE
#   然后执行: launchctl unload ~/Library/LaunchAgents/com.daily-audio-pipeline.plist
#            launchctl load   ~/Library/LaunchAgents/com.daily-audio-pipeline.plist

set -o pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$HOME/Documents/daily-audio-pipeline"
PYTHON="/Applications/anaconda3/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"

export TTS_ENGINE="edge-tts"

PROJECT_DIR="$HOME/Documents/daily-audio-pipeline"
OUTPUT_DIR="$PROJECT_DIR/output"
LOG="$OUTPUT_DIR/pipeline.log"

cd "$PROJECT_DIR" || exit 1
mkdir -p "$OUTPUT_DIR"

# ── 并发保护：确保同一时间只有一个管道实例运行 ──
LOCK_FILE="/tmp/daily-audio-pipeline.lock"
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "⚠️ 另一个管道实例正在运行，跳过本次执行" >> "$LOG"
    exit 0
fi

echo "===== $(date) =====" >> "$LOG"

# ── 日志轮转：超过 5MB 时归档 ──
MAX_LOG_SIZE=$((5 * 1024 * 1024))
if [ -f "$LOG" ] && [ "$(stat -f%z "$LOG" 2>/dev/null || echo 0)" -gt "$MAX_LOG_SIZE" ]; then
    mv -f "$LOG" "${LOG}.1"
    echo "📋 日志已轮转" >> "$LOG"
fi

# 清理 3 天前的音频文件（保留所有 .txt 文字稿和近 3 天的音频）
echo "清理旧音频文件（>3天）..." >> "$LOG"
find "$OUTPUT_DIR" -maxdepth 1 -name "*.wav" -mtime +3 -delete 2>/dev/null || true
find "$OUTPUT_DIR" -maxdepth 1 -name "*.mp3" -mtime +3 -delete 2>/dev/null || true
find "$OUTPUT_DIR" -maxdepth 1 -name "*.aiff" -mtime +3 -delete 2>/dev/null || true

# 读取数据源模式（安全方式，不拼接路径到 Python 字符串中）
CURRENT_MODE="horizon"
MODE_FILE="$PROJECT_DIR/mode.json"
if [ -f "$MODE_FILE" ]; then
    CURRENT_MODE=$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1])).get('mode','horizon'))" "$MODE_FILE" 2>/dev/null) || CURRENT_MODE="horizon"
fi

if [ "$CURRENT_MODE" = "horizon" ]; then
    echo "运行 Horizon 新闻聚合（消耗 token）..." >> "$LOG"
    HORIZON_DIR="$HOME/Documents/Horizon"
    if [ -d "$HORIZON_DIR" ]; then
        export PATH="$HOME/.local/bin:$HORIZON_DIR/.venv/bin:$PATH"
        export HORIZON_SKIP_ENRICH=1
        cd "$HORIZON_DIR" && uv run horizon --hours 24 >> "$LOG" 2>&1
        HORIZON_EXIT=$?
        if [ $HORIZON_EXIT -ne 0 ]; then
            echo "⚠️ Horizon 退出码: $HORIZON_EXIT" >> "$LOG"
        fi
        echo "Horizon 完成" >> "$LOG"
        cd "$PROJECT_DIR" || exit 1
    else
        echo "⚠️ Horizon 目录不存在: $HORIZON_DIR" >> "$LOG"
    fi
else
    echo "伯乐Skill模式（无 token 消耗）" >> "$LOG"
fi

"$PYTHON" daily_pipeline.py >> "$LOG" 2>&1
PIPELINE_OK=$?

if [ $PIPELINE_OK -ne 0 ]; then
    echo "⚠️ Pipeline 退出码: $PIPELINE_OK" >> "$LOG"
    # P1-4: 失败时发送 macOS 系统通知
    osascript -e 'display notification "每日语音播报执行失败，请检查日志" with title "⚠️ 播报失败" subtitle "Pipeline 退出码: '"$PIPELINE_OK"'"' 2>/dev/null || true
fi

echo "===== 完成 =====" >> "$LOG"

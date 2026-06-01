#!/bin/bash
# 每日语音播报 · 启动台
# 第一次启动会启动仪表盘服务，之后只是打开页面

PYTHON="/Applications/anaconda3/bin/python3"
SCRIPT="$HOME/Documents/daily-audio-pipeline/dashboard.py"
URL="http://127.0.0.1:8765"

if pgrep -f "dashboard.py" > /dev/null 2>&1; then
    echo "✅ 仪表盘已在运行，打开页面..."
    open "$URL"
    exit 0
fi

echo "🚀 启动每日语音播报仪表盘..."
export TTS_ENGINE="edge-tts"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$HOME/Documents/daily-audio-pipeline" || exit 1
nohup "$PYTHON" "$SCRIPT" > "$HOME/Documents/daily-audio-pipeline/output/dashboard.log" 2>&1 &
sleep 2
open "$URL"
echo "✅ 仪表盘已启动"
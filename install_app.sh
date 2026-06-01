#!/bin/bash

# ─── Daily Audio Pipeline 安装 / 更新脚本 ───────────────

GREEN='\033[0;32m'
CYAN='\033[0;36m'
AMBER='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

APP_NAME="DailyAudioPipeline"
APP_BUNDLE="$HOME/Applications/$APP_NAME.app"
APP_DIR="$APP_BUNDLE/Contents/MacOS"
RES_DIR="$APP_BUNDLE/Contents/Resources"

PYTHON_EXE="/Applications/anaconda3/bin/python3"
SCRIPT_PATH="$HOME/Documents/daily-audio-pipeline/dashboard.py"
ICON_SRC="$HOME/Documents/daily-audio-pipeline/AppIcon.icns"

echo -e "${CYAN}═══ 每日播报仪表盘 · 安装/更新 ═══${NC}"
echo ""

# 1. 确保项目路径存在
if [ ! -f "$SCRIPT_PATH" ]; then
    echo -e "${RED}❌ 未找到启动脚本: $SCRIPT_PATH${NC}"
    echo "请确认项目位于 ~/Documents/daily-audio-pipeline/"
    exit 1
fi

# 2. 创建 app 包结构
mkdir -p "$APP_DIR" "$RES_DIR"

# 3. Info.plist
cat > "$APP_BUNDLE/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>dashboard</string>
    <key>CFBundleIdentifier</key>
    <string>com.daily-audio-pipeline.dashboard</string>
    <key>CFBundleName</key>
    <string>DailyAudioPipeline</string>
    <key>CFBundleDisplayName</key>
    <string>每日播报仪表盘</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

# 4. 启动脚本
cat > "$APP_DIR/dashboard" <<'EXEC'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TTS_ENGINE="edge-tts"
cd "$HOME/Documents/daily-audio-pipeline" || exit 1
/Applications/anaconda3/bin/python3 dashboard.py
EXEC
chmod +x "$APP_DIR/dashboard"

# 5. 安装图标
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$RES_DIR/AppIcon.icns"
    echo -e "${GREEN}✅ 图标已安装${NC}"
else
    echo -e "${AMBER}⚠️  未找到图标文件 $ICON_SRC，使用默认图标${NC}"
fi

# 6. 刷新缓存
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP_BUNDLE" &>/dev/null

echo ""
echo -e "${GREEN}✅ 应用已更新: $APP_BUNDLE${NC}"
echo ""
echo -e "${CYAN}操作指南：${NC}"
echo "  1. 现在双击 Applications 里的「每日播报仪表盘」启动"
echo "  2. 或加入登录项实现开机自启："
echo "     系统设置 → 通用 → 登录项 → + → 搜索 DailyAudioPipeline"
echo ""
echo -e "${CYAN}如果图标未立即显示：${NC}"
echo "  重启 Finder: 按住 Option 右键点击 Finder 图标 → 重新开启"
echo "  或登出再登入"
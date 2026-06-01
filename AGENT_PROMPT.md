# Daily Audio Pipeline — AI Agent 引导提示词

## 项目位置
```
/Users/dongyue/Documents/daily-audio-pipeline/
```

## 一句话
每天早上自动抓取技术新闻 → AI 筛选评分 → 中文口播稿 → Edge TTS 语音合成 → 推送到 HomePod Mini「玄珠」播放。

## 架构总览
```
用户触发 ───→ daily_pipeline.py（主编排器）
                  │
          ┌───────┴───────┐
          ▼               ▼
  HorizonAdapter      BoleSkillAdapter
  (消耗 token)         (免费, 缓存)
          │               │
          └───────┬───────┘
                  ▼
         build_script() → 口播稿
                  │
                  ▼
           TTS引擎 → MP3音频
                  │
                  ▼
       AirPlayPlayer → HomePod「玄珠」
         (pyatv RAOP 推流)
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `daily_pipeline.py` | 主编排器：选数据源→写稿→合成→播放 |
| `dashboard.py` | Flask 仪表盘 (port 8765)：管理界面+后台调度器 |
| `templates/dashboard.html` | 科幻风格前端 |
| `config.py` | 配置参数（时间、TTS、条数等） |
| `mode.json` | `{"mode":"horizon"}` 或 `{"mode":"bole"}` |
| `run_daily.sh` | 定时播报执行脚本 |
| `players/base.py` | AirPlay 推流播放器（pyatv → HomePod） |
| `adapters/horizon_adapter.py` | 解析 Horizon 日报 |
| `adapters/bole_skill.py` | 伯乐Skill 数据获取（有本地缓存） |
| `engines/tts.py` | 语音合成引擎 |
| `test_airplay.py` | AirPlay 测试脚本 |
| `generate_icon.py` | 生成 app 图标 |
| `install_app.sh` | 安装 macOS app 包 |
| `com.dashboard.plist` | launchd 自启动配置（可选） |
| `每日语音管道.command` | 桌面启动脚本 |
| `output/pipeline.log` | 运行时日志 |

## 数据源

### Horizon 模式（默认）
- 多源：HN / RSS / Reddit / Telegram / GitHub / OSS Insight
- 需要 DeepSeek API key（在 `~/Documents/Horizon/.env` 中设置）
- 每次运行消耗 token
- 跳过 enrichment 可省约 70% token（设环境变量 `HORIZON_SKIP_ENRICH=1`）

### 伯乐Skill 模式（免费）
- 单一源：`https://raw.githubusercontent.com/LearnPrompt/ai-news-radar/master/data/latest-24h.json`
- 无 token 消耗
- 有本地缓存（1小时 TTL）：`output/.bole_cache.json`

## 中文播报逻辑
1. `horizon_adapter.py` 解析时默认 `lang="zh"`
2. `daily_pipeline.py` 的 `build_script()` 优先取 `title_zh` 和 `summary_zh`
3. Edge TTS 声线：`zh-CN-XiaoxiaoNeural`
4. 口播格式："早上好，今天是 X年X月X日。以下是今天的新闻摘要。\n第1条。标题。摘要。"

## 播放方式
- **优先**：pyatv AirPlay 2 → HomePod Mini「玄珠」(192.168.18.202)
- **回退**：Mac 扬声器（afplay）
- **静音刷新**：播报完成后发 0.3s 静音 WAV 释放 HomePod 音频通道

## 定时机制
- **内部调度器**：`dashboard.py` 后台线程（每 30 秒检查一次）
- 由仪表盘界面控制：暂停 / 恢复 / 改时间
- 默认：每天 8:40（可通过仪表盘修改）
- `run_daily.sh` 是实际执行脚本，由调度器触发

## 仪表盘 API
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/status` | GET | 系统状态 |
| `/api/config` | GET/POST | 读写配置 |
| `/api/play-now` | POST | 触发播报 |
| `/api/play-stop` | POST | 停止播报 |
| `/api/pipeline-log` | GET | 最近 50 行日志 |
| `/api/sources` | GET/POST | 信号源管理 |
| `/api/history` | GET | 历史记录 |
| `/api/schedule` | GET/POST | 定时控制（暂停/恢复/改时间）|
| `/api/source-mode` | GET/POST | 数据源模式切换 |

## 启动方式
- **桌面脚本**：双击 `~/Desktop/每日语音管道.command`
- **macOS app**：双击 `~/Applications/DailyAudioPipeline.app`
- **手动终端**：`cd ~/Documents/daily-audio-pipeline && python3 dashboard.py`
- **开机自启**：加入系统设置 → 通用 → 登录项

## 关键配置（config.py）
- `TARGET_MINUTES`：目标播报时长（分钟）
- `MAX_NEWS_ITEMS`：最大新闻条数
- `AI_RELEVANCE_THRESHOLD`：AI 筛选阈值
- `SCHEDULE_HOUR` / `SCHEDULE_MINUTE`：定时时间
- `TTS_ENGINE`：引擎（edge-tts / say / openai）

## 依赖
| 包 | 用途 |
|----|------|
| flask | 仪表盘 |
| edge-tts | 语音合成 |
| pyatv | AirPlay 2 推流 |
| Pillow | 图标生成 |
| (Horizon 项目) | 多源新闻聚合 |

## 已知注意事项
1. Horizon 项目在 `~/Documents/Horizon/`
2. `mode.json` 控制数据源，仪表盘界面可切换
3. 播放到 HomePod 无需系统音频切换，pyatv 直接推流
4. 仪表盘空闲内存约 5MB，可常驻后台
5. 图标用 `generate_icon.py` 重新生成
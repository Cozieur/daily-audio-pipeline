import asyncio
import shutil
import subprocess
import tempfile
import time
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union


# ── HomePod config ────────────────────────────────────────
HOMEPOD_NAME = "玄珠"

# 超时与重试配置
AIRPLAY_SCAN_TIMEOUT = 10       # 扫描设备超时（秒）
AIRPLAY_CONNECT_TIMEOUT = 15    # 连接设备超时（秒）
AIRPLAY_STREAM_TIMEOUT = 600    # 推流超时（秒，10分钟足够长音频）
AIRPLAY_MAX_RETRIES = 2         # AirPlay 连接重试次数
AIRPLAY_RETRY_DELAY = 3         # 重试间隔（秒）
AFPLAY_TIMEOUT = 600            # afplay 超时（秒）

# 静音刷新音时长（秒），用于 RAOP 流结束后刷新 HomePod 音频状态
SILENCE_FLUSH_SECONDS = 0.3


def _generate_silence_wav(duration: float = SILENCE_FLUSH_SECONDS) -> str:
    temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sample_rate = 44100
    channels = 2
    sample_width = 2
    num_samples = int(sample_rate * duration)
    with wave.open(temp.name, "w") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * num_samples * channels)
    return temp.name


class OutputPlayer(ABC):
    @abstractmethod
    def play(self, audio_path: Union[str, Path]) -> None:
        ...


class AirPlayPlayer(OutputPlayer):
    """Play audio through HomePod Mini via AirPlay 2, with afplay fallback."""

    def __init__(self, save_dir: Union[str, Path, None] = None):
        self._save_dir = Path(save_dir) if save_dir else None

    def play(self, audio_path: Union[str, Path]) -> None:
        audio_path = Path(audio_path)

        if self._save_dir:
            self._save_dir.mkdir(parents=True, exist_ok=True)
            dest = self._save_dir / audio_path.name
            if audio_path.resolve() != dest.resolve():
                shutil.copy2(str(audio_path), str(dest))
                print(f"音频已保存: {dest}")

        played = self._play_via_airplay(audio_path)
        if not played:
            self._play_via_afplay(audio_path)

    def _play_via_airplay(self, audio_path: Path) -> bool:
        try:
            from pyatv import scan, connect

            async def _run_airplay() -> None:
                loop = asyncio.get_running_loop()

                # pyatv 0.17 要求显式传入 loop
                devices = await asyncio.wait_for(
                    scan(loop, timeout=AIRPLAY_SCAN_TIMEOUT),
                    timeout=AIRPLAY_SCAN_TIMEOUT + 5,
                )
                target = None
                for d in devices:
                    if HOMEPOD_NAME in d.name:
                        target = d
                        break

                if not target:
                    print(f"⚠️ 未找到 HomePod「{HOMEPOD_NAME}」，使用扬声器播放")
                    return

                print(f"✅ 已发现 HomePod: {target.name} ({target.address})")

                silence_wav = _generate_silence_wav()

                async def _stream_one(file_path: str) -> None:
                    session = await asyncio.wait_for(
                        connect(target, loop), timeout=AIRPLAY_CONNECT_TIMEOUT
                    )
                    try:
                        await asyncio.wait_for(
                            session.stream.stream_file(file_path),
                            timeout=AIRPLAY_STREAM_TIMEOUT,
                        )
                    finally:
                        session.close()

                last_error = None
                for attempt in range(1, AIRPLAY_MAX_RETRIES + 1):
                    try:
                        print(f"🔊 正在推送到「{target.name}」...（第{attempt}次）")
                        await _stream_one(str(audio_path))
                        print(f"🔄 发送静音刷新信号...")
                        await _stream_one(silence_wav)
                        print(f"✅ 播放完成")
                        Path(silence_wav).unlink(missing_ok=True)
                        return
                    except (asyncio.TimeoutError, OSError, ConnectionError) as e:
                        last_error = e
                        if attempt < AIRPLAY_MAX_RETRIES:
                            print(f"⚠️ 推送失败（{e}），{AIRPLAY_RETRY_DELAY}s 后重试...")
                            await asyncio.sleep(AIRPLAY_RETRY_DELAY)
                        else:
                            Path(silence_wav).unlink(missing_ok=True)
                            raise last_error

            asyncio.run(_run_airplay())
            return True

        except ImportError:
            print("⚠️ pyatv 未安装，使用扬声器播放")
            return False
        except asyncio.TimeoutError:
            print(f"⚠️ AirPlay 推送超时，使用扬声器播放")
            return False
        except RuntimeError as e:
            # scan 未找到设备时 _run_airplay 正常返回，不进入此分支
            print(f"⚠️ AirPlay 运行时错误（{e}），使用扬声器播放")
            return False
        except Exception as e:
            print(f"⚠️ AirPlay 播放失败（{e}），使用扬声器播放")
            return False

    def _play_via_afplay(self, audio_path: Path) -> None:
        print(f"🔊 通过系统扬声器播放: {audio_path}")
        subprocess.run(
            ["afplay", str(audio_path)],
            check=True,
            timeout=AFPLAY_TIMEOUT,
        )

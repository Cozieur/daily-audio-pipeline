import asyncio
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

from config import SAY_VOICE, SAY_RATE

# TTS 超时配置
SAY_TIMEOUT = 120       # macOS say 超时（秒）
FFMPEG_TIMEOUT = 60     # ffmpeg 转码超时（秒）
EDGE_TTS_TIMEOUT = 180  # edge-tts 合成超时（秒）


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: Union[str, Path]) -> str:
        ...


class SayTTSEngine(TTSEngine):
    def __init__(self, voice: str = SAY_VOICE, rate: str = SAY_RATE):
        self._voice = voice
        self._rate = rate

    def synthesize(self, text: str, output_path: Union[str, Path]) -> str:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        aiff_path = output_path.with_suffix(".aiff")
        cmd = [
            "say",
            "-v", self._voice,
            "-r", self._rate,
            "-o", str(aiff_path),
        ]
        subprocess.run(
            cmd, input=text.encode("utf-8"), check=True, timeout=SAY_TIMEOUT,
        )

        wav_path = output_path.with_suffix(".wav")
        ffmpeg_cmd = "ffmpeg"
        if not shutil.which("ffmpeg"):
            ffmpeg_cmd = "/opt/homebrew/bin/ffmpeg"
        subprocess.run([
            ffmpeg_cmd, "-y", "-i", str(aiff_path),
            "-acodec", "pcm_s16le", "-ar", "44100",
            "-ac", "2", str(wav_path),
        ], capture_output=True, check=True, timeout=FFMPEG_TIMEOUT)

        aiff_path.unlink(missing_ok=True)
        return str(wav_path)


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self._voice = voice

    def synthesize(self, text: str, output_path: Union[str, Path]) -> str:
        import edge_tts

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        mp3_path = output_path.with_suffix(".mp3")
        communicate = edge_tts.Communicate(text, self._voice)

        async def _save_with_timeout() -> None:
            await asyncio.wait_for(
                communicate.save(str(mp3_path)),
                timeout=EDGE_TTS_TIMEOUT,
            )

        asyncio.run(_save_with_timeout())
        return str(mp3_path)


def create_tts_engine(engine_name: str = "say", voice: str = "") -> TTSEngine:
    if engine_name == "edge-tts":
        edge_voice = voice if voice and voice.startswith("zh-CN-") else "zh-CN-XiaoxiaoNeural"
        return EdgeTTSEngine(voice=edge_voice)
    return SayTTSEngine()

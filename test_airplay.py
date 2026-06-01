#!/usr/bin/env python3
"""综合测试：推流到 HomePod Mini + 静音刷新"""
import asyncio
import tempfile
import wave
from pathlib import Path

HOMEPOD_NAME = "玄珠"

def _generate_silence_wav(duration: float = 0.3) -> str:
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

async def test():
    from pyatv import scan, connect
    from edge_tts import Communicate

    print("🔍 扫描 HomePod...")
    devices = await scan(loop=asyncio.get_event_loop(), timeout=5)
    target = None
    for d in devices:
        if HOMEPOD_NAME in d.name:
            target = d
            print(f"  ✅ 找到: {d.name} ({d.address})")
            break
    if not target:
        print("❌ 未找到"); return

    # 生成测试音频
    mp3_file = Path("/tmp/test_airplay.mp3")
    await Communicate(
        "新闻测试音频。这是一个测试。一二三四五六七八九十。",
        "zh-CN-XiaoxiaoNeural"
    ).save(str(mp3_file))
    print(f"✅ 测试音频: {mp3_file} ({mp3_file.stat().st_size} bytes)")

    silence_wav = _generate_silence_wav(0.3)
    print(f"✅ 静音刷新音: {silence_wav}")

    async def _stream_one(file_path: str) -> None:
        session = await connect(target, loop=asyncio.get_event_loop())
        try:
            await session.stream.stream_file(file_path)
        finally:
            session.close()

    print(f"\n🔊 步骤1: 推流主音频...")
    await _stream_one(str(mp3_file))
    print("  ✅ 主音频推流完成")

    print(f"\n🔄 步骤2: 推流静音刷新信号...")
    await _stream_one(silence_wav)
    print("  ✅ 静音刷新完成")

    Path(silence_wav).unlink(missing_ok=True)
    print(f"\n✅ 全部完成！请测试：现在用手机投送视频到玄珠，音频应该正常了")

if __name__ == "__main__":
    asyncio.run(test())
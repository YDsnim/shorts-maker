# =====================================================
# auto_pipeline/generate_voice.py
# edge-tts로 한국어 TTS 음성 파일을 생성합니다.
#
# edge-tts는 Microsoft Edge TTS 서버를 사용하며 완전 무료입니다.
# gTTS보다 훨씬 자연스러운 한국어 발음을 제공합니다.
#
# 설치: pip install edge-tts
# 목소리 목록 확인: python -m edge_tts --list-voices | grep ko-KR
# =====================================================

import asyncio
import json
import subprocess
import edge_tts


async def _tts_async(text: str, output_path: str, voice: str, rate: str) -> None:
    """edge-tts 비동기 실행 내부 함수 (asyncio.run()으로 호출)"""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(output_path)


def generate_voice(text: str, output_path: str,
                   voice: str = 'ko-KR-SunHiNeural',
                   rate: str = '+0%') -> None:
    """
    텍스트를 음성으로 변환해 mp3 파일로 저장합니다.

    text:        대본 텍스트
    output_path: 저장할 mp3 파일 경로
    voice:       edge-tts 목소리 ID
    rate:        말하기 속도 ('+0%' = 기본, '+20%' = 빠름, '-10%' = 느림)
    """
    try:
        asyncio.run(_tts_async(text, output_path, voice, rate))
    except RuntimeError:
        # 이미 이벤트 루프가 실행 중인 환경 (Jupyter 등)에서의 처리
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_tts_async(text, output_path, voice, rate))
        finally:
            loop.close()


def get_audio_duration(audio_path: str) -> float:
    """
    ffprobe로 오디오 파일의 길이(초)를 조회합니다.
    배경 영상을 잘라낼 때 기준 길이로 사용합니다.
    """
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        data = json.loads(result.stdout)
        return float(data.get('format', {}).get('duration', 0))
    except (json.JSONDecodeError, ValueError):
        return 0.0

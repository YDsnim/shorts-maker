# =====================================================
# modules/tts.py
# Google TTS(gTTS)를 이용한 나레이션 생성 모듈
# - 인터넷 연결 필요 (무료, API 키 불필요)
# - edge-tts는 Microsoft 서버가 403을 반환해 사용 불가
# =====================================================

import uuid
import os
import tempfile

from gtts import gTTS


def generate_narration(text: str, voice: str = 'ko', **kwargs) -> str:
    """
    텍스트를 음성(MP3)으로 변환합니다.
    voice: 언어 코드 (기본 'ko' = 한국어)
           'ko-slow' 를 넘기면 느리게 읽습니다.
    반환값: 생성된 .mp3 파일 경로 (사용 후 삭제 필요)
    """
    output_path = os.path.join(tempfile.gettempdir(), f'tts_{uuid.uuid4().hex}.mp3')

    # voice 값에 '-slow' 가 붙어있으면 느린 속도로 읽기
    slow = voice.endswith('-slow')
    lang = voice.replace('-slow', '') if slow else voice

    tts = gTTS(text=text, lang=lang, slow=slow)
    tts.save(output_path)

    return output_path

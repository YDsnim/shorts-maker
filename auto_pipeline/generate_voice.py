# =====================================================
# auto_pipeline/generate_voice.py
# Google Cloud TTS (Neural2)로 한국어 음성 파일을 생성합니다.
#
# 인증: GOOGLE_APPLICATION_CREDENTIALS 환경변수에 JSON 파일 경로 지정
# 무료 한도: Neural2 월 100만자
#
# 목소리 목록 (숏츠 추천):
#   ko-KR-Neural2-C - 여성, 자연스럽고 또렷함  ← 기본값
#   ko-KR-Neural2-A - 여성, 밝고 친근함
#   ko-KR-Neural2-B - 남성, 안정적
#   ko-KR-Neural2-D - 남성, 젊고 활기참
# =====================================================

import json
import subprocess
from google.cloud import texttospeech
from google.oauth2 import service_account


def generate_voice(text: str, output_path: str,
                   speaker: str = 'ko-KR-Neural2-C',
                   speed: float = 1.0,
                   pitch: float = 0.0) -> None:
    """
    Google Cloud TTS Neural2로 텍스트를 음성 파일로 저장합니다.

    text:        대본 텍스트
    output_path: 저장할 mp3 파일 경로
    speaker:     목소리 ID (기본: ko-KR-Neural2-C)
    speed:       말하기 속도 (0.25~4.0, 1.0=기본)
    pitch:       음높이 semitone (-20.0~20.0, 0.0=기본)
    """
    import os
    credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')

    if credentials_path:
        credentials = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )
        client = texttospeech.TextToSpeechClient(credentials=credentials)
    else:
        client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code='ko-KR',
        name=speaker,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speed,
        pitch=pitch,
    )

    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )

    with open(output_path, 'wb') as f:
        f.write(response.audio_content)


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

# =====================================================
# config.py - 앱 전체 설정값 모음
# 나중에 Claude API, 이미지 생성 API 키도 여기에 추가하면 됩니다
# =====================================================

import os

# ── 기본 경로 설정 ──────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')   # 업로드된 원본 파일 저장
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'output')    # 처리 완료 파일 저장

# ── 업로드 제한 ─────────────────────────────────────
MAX_CONTENT_LENGTH = 500 * 1024 * 1024   # 최대 업로드 크기: 500MB
ALLOWED_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv', 'webm'}

# ── 영상 처리 기본값 ────────────────────────────────
SHORTS_WIDTH = 1080    # 유튜브 숏츠 권장 가로 해상도
SHORTS_HEIGHT = 1920   # 유튜브 숏츠 권장 세로 해상도
SHORTS_RATIO = 9 / 16  # 9:16 비율

# ── 자막 스타일 기본값 ──────────────────────────────
SUBTITLE_FONT_SIZE = 18        # 자막 글자 크기 (pt)
SUBTITLE_FONT_COLOR = 'white'  # 자막 글자 색
SUBTITLE_OUTLINE_COLOR = 'black'  # 자막 외곽선 색

# ── TTS 기본값 ──────────────────────────────────────
DEFAULT_TTS_VOICE = 'ko'         # 기본 한국어 (Google TTS)
TTS_VOICES = {
    '한국어 (보통 속도)': 'ko',
    '한국어 (느리게)':   'ko-slow',
}

# ── 파일 보관 TTL ───────────────────────────────────
OUTPUT_TTL_SECONDS = 3600   # output/ 파일 보관 시간 (기본 1시간)

# ── 미래 확장용 API 설정 (지금은 비워둠) ────────────
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY', '')
IMAGE_GEN_API_KEY = os.environ.get('IMAGE_GEN_API_KEY', '')

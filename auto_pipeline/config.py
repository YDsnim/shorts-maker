# =====================================================
# auto_pipeline/config.py — 영상 창작 파이프라인 설정
#
# 이 파일에서 API 키, 목소리, 해상도 등 모든 설정을 관리합니다.
# 환경변수로 주입하거나 이 파일에서 직접 수정하세요.
# =====================================================

import os
import sys

# 부모 폴더(shorts-maker/)의 공유 설정을 가져옵니다
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config as _base

# ── 경로 ─────────────────────────────────────────────
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR     = os.path.join(PIPELINE_DIR, 'temp')   # 중간 파일 임시 저장
OUTPUT_DIR   = _base.OUTPUT_FOLDER                   # 완성 영상은 기존 output/ 공유

os.makedirs(TEMP_DIR, exist_ok=True)

# ── API 키 (환경변수로 주입 권장) ──────────────────────
# 터미널에서: export CLAUDE_API_KEY=sk-ant-...
# 또는 .env 파일에 넣고 dotenv 사용 (pip install python-dotenv)
CLAUDE_API_KEY  = _base.CLAUDE_API_KEY                         # 대본 생성 (유료, 편당 ~1~2원)

# ── TTS (Google Cloud Neural2) ───────────────────────
# 목소리: ko-KR-Neural2-C(여/또렷), A(여/밝음), B(남/안정), D(남/활기)
TTS_VOICE = os.environ.get('GOOGLE_TTS_SPEAKER', 'ko-KR-Neural2-C')
TTS_RATE  = float(os.environ.get('GOOGLE_TTS_SPEED', '1.0'))  # 0.25~4.0

# ── 영상 해상도 ──────────────────────────────────────
TARGET_WIDTH  = _base.SHORTS_WIDTH    # 1080
TARGET_HEIGHT = _base.SHORTS_HEIGHT   # 1920

# ── Claude 모델 ──────────────────────────────────────
# haiku: 가장 저렴하고 빠름 (대본 생성에 충분)
CLAUDE_MODEL = 'claude-sonnet-4-6'

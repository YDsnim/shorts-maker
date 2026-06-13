# =====================================================
# modules/template.py
# 숏츠 비주얼 템플릿 — 모든 디자인 수치의 단일 정의처
# =====================================================

import os

_BASE       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR   = os.path.join(_BASE, 'fonts')
_GMARKET    = os.path.join(FONTS_DIR, 'GmarketSansBold.ttf')
_PRETENDARD = os.path.join(FONTS_DIR, 'Pretendard-ExtraBold.otf')
_MALGUN_B   = r'C:\Windows\Fonts\malgunbd.ttf'   # 맑은 고딕 Bold (시스템 폴백)
_MALGUN     = r'C:\Windows\Fonts\malgun.ttf'


def _pick_font() -> tuple:
    """로드 가능한 첫 번째 한글 폰트 (경로, 이름) 반환"""
    from PIL import ImageFont
    candidates = [
        (_GMARKET,    'GmarketSans Bold'),
        (_PRETENDARD, 'Pretendard ExtraBold'),
        (_MALGUN_B,   'Malgun Gothic Bold'),
        (_MALGUN,     'Malgun Gothic'),
    ]
    for path, name in candidates:
        if os.path.exists(path):
            try:
                ImageFont.truetype(path, 20)
                return path, name
            except Exception:
                continue
    return _MALGUN_B, 'Malgun Gothic Bold'

# ── 폰트 ─────────────────────────────────────────────
FONT_FILE, FONT_NAME = _pick_font()

# ── 영상 규격 ─────────────────────────────────────────
VIDEO_W = 1080
VIDEO_H = 1920

# ── 공통 색상 ─────────────────────────────────────────
COLOR_WHITE_RGB  = (255, 255, 255)
COLOR_YELLOW_RGB = (255, 204,   0)   # #FFCC00
COLOR_WHITE_ASS  = '&H00FFFFFF&'
COLOR_YELLOW_ASS = '&H0000CCFF&'

# ── 자막 공통 ─────────────────────────────────────────
SUBTITLE_FONT_SIZE = 65
SUBTITLE_OUTLINE   = 3
SUBTITLE_SHADOW    = 1
SUBTITLE_MARGIN_V  = 160   # 기본(namnam) 기준

# ── 배너 공통 ─────────────────────────────────────────
BANNER_H         = 240
BANNER_BG_RGB    = (17, 17, 17)
BANNER_FONT_SIZE = 60

# =====================================================
# 템플릿 정의
# =====================================================

TEMPLATES = {
    'namnam': {
        'label':           '냠냠코기 스타일',
        # 단색 배경
        'bg_color':        (17, 17, 17),
        # 상단 배너 (Pillow 생성)
        'banner_h':        240,
        'banner_bg':       (17, 17, 17),
        'banner_font_size': 60,
        # 영상 삽입 위치 (배너 바로 아래)
        'video_y':         240,
        # 자막 (배너+영상 아래 여백)
        'subtitle_font_size': 55,
        'subtitle_margin_v':  200,
    },
    'silver_crown': {
        'label':            '실버크라운',
        # 배경 PNG 경로 (정적 이미지 전체 배경)
        'bg_png':           os.path.join(_BASE, 'static', 'templates', 'silver_crown.png'),
        # 중앙 영상 삽입 y 좌표 (가로 1080px 꽉 채움)
        'video_y':          580,
        # 제목 텍스트 (상단, 중앙 정렬)
        'title_y':          320,
        'title_font_size':  65,
        'title_max_width':  960,
        # 자막 (50pt, y=1380 위치)
        'subtitle_font_size': 50,
        'subtitle_margin_v':  470,
        # 출처 텍스트 (최하단 고정)
        'source_text':      '출처: 실버크라운',
        'source_y':         1620,
        'source_font_size': 40,
    },
}

DEFAULT_TEMPLATE = 'namnam'


def get_template(key: str) -> dict:
    return TEMPLATES.get(key, TEMPLATES[DEFAULT_TEMPLATE])

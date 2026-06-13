# =====================================================
# modules/subtitle.py
# 자막 생성 및 영상에 삽입하는 모듈
# - ASS 형식 자막 생성 (핵심어 노란색 강조 지원)
# - ffmpeg로 자막을 영상에 굽기 (하드코딩)
# =====================================================

import os
import uuid
import subprocess
import tempfile

from modules.template import (
    FONTS_DIR, FONT_FILE, FONT_NAME,
    SUBTITLE_FONT_SIZE, SUBTITLE_OUTLINE, SUBTITLE_SHADOW, SUBTITLE_MARGIN_V,
    COLOR_WHITE_ASS, COLOR_YELLOW_ASS,
    get_template,
)


def create_srt_file(text: str, video_duration: float) -> str:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        lines = [text.strip()]

    time_per_line = video_duration / len(lines)
    time_per_line = max(1.0, min(time_per_line, 5.0))

    srt_path = os.path.join(tempfile.gettempdir(), f'sub_{uuid.uuid4().hex}.srt')

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, line in enumerate(lines):
            start_sec = i * time_per_line
            end_sec   = start_sec + time_per_line
            f.write(f"{i + 1}\n")
            f.write(f"{_sec_to_srt(start_sec)} --> {_sec_to_srt(end_sec)}\n")
            f.write(f"{line}\n\n")

    return srt_path


def build_ass_file(blocks: list, ass_path: str, tpl_key: str = 'namnam',
                   positions: dict = None, styles: dict = None) -> None:
    tpl      = get_template(tpl_key)
    pos      = positions or {}
    sty      = styles    or {}
    fs       = sty.get('subtitle_font_size', tpl.get('subtitle_font_size', SUBTITLE_FONT_SIZE))
    margin_v = pos.get('subtitle_margin_v',  tpl.get('subtitle_margin_v',  SUBTITLE_MARGIN_V))

    header = f"""\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{fs},{COLOR_WHITE_ASS},&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,{SUBTITLE_OUTLINE},{SUBTITLE_SHADOW},2,20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header)
        for block in blocks:
            start = _sec_to_ass(block['start'])
            end   = _sec_to_ass(block['end'])
            text  = block['text']
            hw    = block.get('highlight')

            if hw and hw in text:
                text = text.replace(hw, f'{{\\c{COLOR_YELLOW_ASS}}}{hw}{{\\c{COLOR_WHITE_ASS}}}', 1)

            text = text.replace('\n', r'\N')
            f.write(f'Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n')


def burn_subtitles(video_path: str, ass_path: str, output_path: str) -> None:
    safe_ass   = ass_path.replace('\\', '/').replace(':', '\\:')
    safe_fonts = FONTS_DIR.replace('\\', '/').replace(':', '\\:')

    if os.path.exists(FONT_FILE):
        vf = f"ass='{safe_ass}':fontsdir='{safe_fonts}'"
    else:
        vf = f"ass='{safe_ass}'"

    cmd = [
        'ffmpeg', '-i', video_path,
        '-vf', vf,
        '-c:a', 'copy',
        '-y', output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        error_lines = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(error_lines))


def _sec_to_srt(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _sec_to_ass(seconds: float) -> str:
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

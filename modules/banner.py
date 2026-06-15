import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont
from modules.template import (
    FONT_FILE, VIDEO_W, VIDEO_H,
    COLOR_YELLOW_RGB, COLOR_WHITE_RGB,
    SUBTITLE_FONT_SIZE, SUBTITLE_MARGIN_V,
    get_template,
)


def _load_font(size: int):
    try:
        return ImageFont.truetype(FONT_FILE, size)
    except Exception:
        return ImageFont.load_default()


def _open_frame(frame_path: str) -> Image.Image:
    """프레임 이미지를 열어 VIDEO_W 너비로 스케일합니다."""
    frame = Image.open(frame_path).convert('RGBA')
    new_h = int(frame.height * VIDEO_W / frame.width)
    return frame.resize((VIDEO_W, new_h), Image.LANCZOS)


def _hex_to_rgb(hex_str: str) -> tuple:
    """#rrggbb 또는 rrggbb → (R, G, B). 파싱 실패 시 흰색."""
    s = (hex_str or '').lstrip('#').strip()
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return COLOR_WHITE_RGB


def _draw_layer_bar(img: Image.Image, text: str, y: int, font, color_rgb: tuple) -> None:
    """가로 전체 너비 바 + 중앙 정렬 텍스트를 img에 직접 합성합니다."""
    draw  = ImageDraw.Draw(img)
    bbox  = font.getbbox('가')
    th    = bbox[3] - bbox[1]
    pad   = max(int(th * 0.45), 16)
    bar_h = th + pad * 2

    bar = Image.new('RGBA', (VIDEO_W, bar_h), (20, 20, 20, 210))
    img.paste(bar, (0, y), bar)

    lw = draw.textlength(text, font=font)
    tx = (VIDEO_W - lw) / 2
    ty = y + pad - bbox[1]
    draw.text((tx, ty), text, font=font, fill=(*color_rgb, 255))


def generate_banner_png(title: str, out_path: str, tpl_key: str = 'namnam',
                        styles: dict = None) -> str:
    """냠냠코기 스타일 상단 배너 PNG 생성"""
    tpl       = get_template(tpl_key)
    sty       = styles or {}
    banner_h  = tpl['banner_h']
    font_size = sty.get('banner_font_size', tpl['banner_font_size'])

    font = _load_font(font_size)
    img  = Image.new('RGBA', (VIDEO_W, banner_h), (*tpl['banner_bg'], 255))
    draw = ImageDraw.Draw(img)

    parts       = title.split(' ', 1)
    yellow_text = parts[0]
    white_text  = (' ' + parts[1]) if len(parts) > 1 else ''

    yw      = draw.textlength(yellow_text, font=font)
    ww      = draw.textlength(white_text,  font=font) if white_text else 0
    x       = (VIDEO_W - yw - ww) / 2
    bbox    = font.getbbox('가')
    text_h  = bbox[3] - bbox[1]
    y       = (banner_h - text_h) / 2 - bbox[1]

    draw.text((x,      y), yellow_text, font=font, fill=COLOR_YELLOW_RGB)
    draw.text((x + yw, y), white_text,  font=font, fill=COLOR_WHITE_RGB)

    img.save(out_path, 'PNG')
    return out_path


def generate_title_overlay_png(title: str, out_path: str, tpl_key: str = 'silver_crown',
                               positions: dict = None, styles: dict = None) -> str:
    """실버크라운 스타일 제목 텍스트 오버레이 PNG (투명 배경, 중앙 정렬)"""
    tpl       = get_template(tpl_key)
    pos       = positions or {}
    sty       = styles    or {}
    font_size = sty.get('title_font_size', tpl['title_font_size'])
    max_width = tpl['title_max_width']
    title_y   = pos.get('title_y', tpl['title_y'])

    font = _load_font(font_size)
    img  = Image.new('RGBA', (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    lines  = _wrap_text(title, font, draw, max_width)
    bbox   = font.getbbox('가')
    line_h = bbox[3] - bbox[1] + 10
    y      = title_y

    for line in lines:
        lw = draw.textlength(line, font=font)
        x  = (VIDEO_W - lw) / 2
        draw.text((x, y), line, font=font, fill=COLOR_WHITE_RGB)
        y += line_h

    img.save(out_path, 'PNG')
    return out_path


def generate_custom_layers_png(layers: list, out_path: str) -> str:
    """커스텀 텍스트 레이어를 가로줄(바) 스타일로 1080×1920 투명 PNG에 렌더링"""
    img = Image.new('RGBA', (VIDEO_W, VIDEO_H), (0, 0, 0, 0))
    for layer in layers:
        text = (layer.get('text') or '').strip()
        if not text:
            continue
        font      = _load_font(int(layer.get('font_size', 50)))
        y         = int(layer.get('y', 500))
        color_rgb = _hex_to_rgb(layer.get('color') or '#FFFFFF')
        _draw_layer_bar(img, text, y, font, color_rgb)
    img.save(out_path, 'PNG')
    return out_path


def generate_template_preview(video_path: str, out_path: str,
                              tpl_key: str = 'namnam', title: str = '',
                              positions: dict = None, styles: dict = None,
                              seek_time: float = 3,
                              custom_layers: list = None) -> str:
    """동영상 프레임에 템플릿 오버레이를 합성해 JPEG 미리보기 생성"""
    positions     = positions     or {}
    custom_layers = custom_layers or []
    frame_tmp = tempfile.mktemp(suffix='_frame.png')
    try:
        r = subprocess.run(
            ['ffmpeg', '-ss', str(seek_time), '-i', video_path, '-frames:v', '1', '-y', frame_tmp],
            capture_output=True,
        )
        if r.returncode != 0 or not os.path.exists(frame_tmp) or os.path.getsize(frame_tmp) == 0:
            subprocess.run(
                ['ffmpeg', '-i', video_path, '-frames:v', '1', '-y', frame_tmp],
                capture_output=True, check=True,
            )
        if tpl_key == 'silver_crown':
            _compose_silver_crown_preview(frame_tmp, out_path, title, positions, styles=styles)
        else:
            _compose_namnam_preview(frame_tmp, out_path, title, positions, styles=styles)

        # 커스텀 레이어 — 가로줄 바 스타일로 합성
        if custom_layers:
            result = Image.open(out_path).convert('RGBA')
            for layer in custom_layers:
                text = (layer.get('text') or '').strip()
                if not text:
                    continue
                font      = _load_font(int(layer.get('font_size', 50)))
                y         = int(layer.get('y', 500))
                color_rgb = _hex_to_rgb(layer.get('color') or '#FFFFFF')
                _draw_layer_bar(result, text, y, font, color_rgb)
            result.convert('RGB').save(out_path, 'JPEG', quality=88)
    finally:
        try:
            os.unlink(frame_tmp)
        except OSError:
            pass
    return out_path


def _compose_namnam_preview(frame_path: str, out_path: str, title: str,
                            positions: dict = None, styles: dict = None) -> None:
    tpl      = get_template('namnam')
    pos      = positions or {}
    sty      = styles    or {}
    video_y  = pos.get('video_y',  tpl.get('video_y', 240))
    banner_h = pos.get('banner_h', tpl.get('banner_h', 240))
    bg_rgb   = tpl.get('bg_color', (17, 17, 17))

    result = Image.new('RGBA', (VIDEO_W, VIDEO_H), (*bg_rgb, 255))
    frame  = _open_frame(frame_path)
    result.paste(frame, (0, video_y), frame)

    font_size = sty.get('banner_font_size', tpl['banner_font_size'])
    font      = _load_font(font_size)
    banner    = Image.new('RGBA', (VIDEO_W, banner_h), (*tpl['banner_bg'], 255))
    draw      = ImageDraw.Draw(banner)
    if title:
        parts       = title.split(' ', 1)
        yellow_text = parts[0]
        white_text  = (' ' + parts[1]) if len(parts) > 1 else ''
        yw     = draw.textlength(yellow_text, font=font)
        ww     = draw.textlength(white_text,  font=font) if white_text else 0
        x      = (VIDEO_W - yw - ww) / 2
        bbox   = font.getbbox('가')
        text_h = bbox[3] - bbox[1]
        y      = (banner_h - text_h) / 2 - bbox[1]
        draw.text((x,      y), yellow_text, font=font, fill=COLOR_YELLOW_RGB)
        draw.text((x + yw, y), white_text,  font=font, fill=COLOR_WHITE_RGB)
    result.paste(banner, (0, 0), banner)

    _draw_subtitle_sample(result, pos, sty, tpl)
    result.convert('RGB').save(out_path, 'JPEG', quality=88)


def _compose_silver_crown_preview(frame_path: str, out_path: str, title: str,
                                  positions: dict = None, styles: dict = None) -> None:
    tpl     = get_template('silver_crown')
    pos     = positions or {}
    sty     = styles    or {}
    bg_png  = tpl['bg_png']
    video_y = pos.get('video_y', tpl['video_y'])
    title_y = pos.get('title_y', tpl['title_y'])

    bg    = Image.open(bg_png).convert('RGBA').resize((VIDEO_W, VIDEO_H), Image.LANCZOS)
    frame = _open_frame(frame_path)
    bg.paste(frame, (0, video_y), frame)

    if title:
        font_size = sty.get('title_font_size', tpl['title_font_size'])
        max_width = tpl['title_max_width']
        font  = _load_font(font_size)
        draw  = ImageDraw.Draw(bg)
        lines = _wrap_text(title, font, draw, max_width)
        bbox  = font.getbbox('가')
        line_h = bbox[3] - bbox[1] + 10
        y = title_y
        for line in lines:
            lw = draw.textlength(line, font=font)
            x  = (VIDEO_W - lw) / 2
            draw.text((x, y), line, font=font, fill=COLOR_WHITE_RGB)
            y += line_h

    _draw_subtitle_sample(bg, pos, sty, tpl)
    bg.convert('RGB').save(out_path, 'JPEG', quality=88)


def _draw_subtitle_sample(img: Image.Image, pos: dict, sty: dict, tpl: dict) -> None:
    """미리보기에 '본문 자막위치' 샘플 텍스트를 자막 위치에 표시"""
    fs       = sty.get('subtitle_font_size', tpl.get('subtitle_font_size', SUBTITLE_FONT_SIZE))
    margin_v = pos.get('subtitle_margin_v',  tpl.get('subtitle_margin_v',  SUBTITLE_MARGIN_V))
    sample   = '본문 자막위치'
    font     = _load_font(fs)
    draw     = ImageDraw.Draw(img)
    bbox     = font.getbbox('가')
    line_h   = bbox[3] - bbox[1]
    text_top = int(VIDEO_H - margin_v - line_h)
    lw       = draw.textlength(sample, font=font)
    x        = (VIDEO_W - lw) / 2
    pad = 8
    draw.rectangle(
        [x - pad, text_top - pad, x + lw + pad, text_top + line_h + pad],
        fill=(0, 0, 0, 120),
    )
    draw.text((x, text_top), sample, font=font, fill=(255, 255, 100, 220))


def _wrap_text(text: str, font, draw, max_width: int) -> list:
    words = text.split(' ')
    lines, buf = [], ''
    for word in words:
        test = (buf + ' ' + word).strip()
        if draw.textlength(test, font=font) <= max_width:
            buf = test
        else:
            if buf:
                lines.append(buf)
            buf = word
    if buf:
        lines.append(buf)
    return lines

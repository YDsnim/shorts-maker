# =====================================================
# modules/video_processor.py
# ffmpeg를 이용한 영상 처리 모듈
# - 영상 정보 추출
# - 9:16 세로 크롭
# - 구간 자르기
# - 오디오 합성
# =====================================================

import subprocess
import json
import os


def get_video_info(filepath: str) -> dict:
    """
    ffprobe로 영상 정보를 읽어옵니다.
    반환값: width, height, duration(초), duration_str(MM:SS)
    """
    cmd = [
        'ffprobe',
        '-v', 'quiet',              # 로그 숨기기
        '-print_format', 'json',    # JSON 형식으로 출력
        '-show_streams',            # 스트림 정보 포함
        '-show_format',             # 포맷 정보 포함
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    data = json.loads(result.stdout)

    # 비디오 스트림만 골라냅니다
    video_stream = next(
        (s for s in data.get('streams', []) if s.get('codec_type') == 'video'),
        None
    )

    if not video_stream:
        return {'width': 0, 'height': 0, 'duration': 0, 'duration_str': '00:00'}

    width = int(video_stream.get('width', 0))
    height = int(video_stream.get('height', 0))
    duration = float(data.get('format', {}).get('duration', 0))

    return {
        'width': width,
        'height': height,
        'duration': round(duration, 2),
        'duration_str': _format_duration(duration),
    }


def _format_duration(seconds: float) -> str:
    """초 단위 숫자를 MM:SS 문자열로 변환합니다."""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def crop_to_vertical(input_path: str, output_path: str) -> None:
    """
    가로 영상을 9:16 세로 비율로 가운데 크롭합니다.
    이미 세로 영상이면 그대로 복사합니다.
    """
    info = get_video_info(input_path)
    w, h = info['width'], info['height']

    target_ratio = 9 / 16  # 숏츠 비율

    if w / h > target_ratio:
        # 가로가 더 넓은 영상 → 좌우를 잘라 세로로 만듦
        new_w = int(h * target_ratio)
        new_h = h
    else:
        # 이미 세로이거나 더 세로인 영상 → 위아래를 잘라 9:16에 맞춤
        new_w = w
        new_h = int(w / target_ratio)

    # ffmpeg는 해상도가 2의 배수여야 합니다
    new_w -= new_w % 2
    new_h -= new_h % 2

    # 크롭 시작 좌표 (가운데 기준)
    x = (w - new_w) // 2
    y = (h - new_h) // 2

    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', f'crop={new_w}:{new_h}:{x}:{y}',
        '-c:a', 'copy',   # 오디오는 그대로 복사
        '-y',             # 덮어쓰기 허용
        output_path
    ]
    _run(cmd)


def trim_video(input_path: str, output_path: str,
               start: float, end: float | None = None) -> None:
    """
    영상의 특정 구간만 잘라냅니다.
    start, end 는 초 단위입니다. end를 생략하면 끝까지 남깁니다.
    """
    cmd = ['ffmpeg', '-ss', str(start), '-i', input_path]

    if end is not None and end > start:
        cmd += ['-t', str(end - start)]

    # copy 코덱을 쓰면 매우 빠르게 처리됩니다 (재인코딩 없음)
    cmd += ['-c', 'copy', '-avoid_negative_ts', '1', '-y', output_path]
    _run(cmd)


def add_audio_to_video(video_path: str, audio_path: str, output_path: str) -> None:
    """
    영상에 TTS 오디오를 덮어씌웁니다.
    기존 오디오가 있으면 TTS 오디오로 교체됩니다.
    영상보다 오디오가 짧으면 오디오 끝에서 영상도 같이 끝납니다.
    """
    cmd = [
        'ffmpeg',
        '-i', video_path,
        '-i', audio_path,
        '-map', '0:v:0',       # 원본 영상 스트림 사용
        '-map', '1:a:0',       # TTS 오디오 스트림 사용
        '-c:v', 'copy',        # 영상은 재인코딩 없이 복사
        '-c:a', 'aac',         # 오디오를 AAC로 인코딩
        '-shortest',           # 둘 중 짧은 쪽 기준으로 종료
        '-y', output_path
    ]
    _run(cmd)


def crop_custom(input_path: str, output_path: str,
                x: int, y: int, w: int, h: int) -> None:
    """
    사용자가 지정한 픽셀 좌표로 영상을 크롭합니다.
    프론트엔드 드래그 UI에서 받은 값을 그대로 사용합니다.
    """
    # ffmpeg는 크기가 2의 배수여야 합니다
    w -= w % 2
    h -= h % 2

    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', f'crop={w}:{h}:{x}:{y}',
        '-c:a', 'copy',
        '-y', output_path
    ]
    _run(cmd)


# ── 새 모드: ffmpeg 커맨드 빌더 (앱에서 백그라운드 스레드로 실행) ───────

def build_crop_cmd(input_path: str, output_path: str,
                   x: int, y: int, w: int, h: int) -> list:
    """
    크롭 ffmpeg 커맨드 리스트를 반환한다 (실행하지 않음).
    -progress pipe:1 옵션으로 앱이 진행률을 stdout에서 읽을 수 있게 한다.
    """
    w -= w % 2
    h -= h % 2
    return [
        'ffmpeg', '-i', input_path,
        '-vf', f'crop={w}:{h}:{x}:{y}',
        '-c:a', 'copy',
        '-progress', 'pipe:1', '-nostats',
        '-y', output_path,
    ]


def build_blur_cmd(input_path: str, output_path: str,
                   blur: int = 20, crop: dict = None,
                   target_w: int = 1080, target_h: int = 1920) -> list:
    """
    블러 배경 ffmpeg 커맨드를 반환한다.

    crop 딕트가 있으면 해당 영역만 전경으로 사용하고,
    없으면 원본 전체를 축소해 가운데에 올린다.
    blur 값이 클수록 배경이 더 흐려진다 (권장: 10~50).
    """
    if crop:
        cx, cy = int(crop['x']), int(crop['y'])
        cw = int(crop['w']) & ~1
        ch = int(crop['h']) & ~1
        fg = (f'[0:v]crop={cw}:{ch}:{cx}:{cy},'
              f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg]')
    else:
        fg = f'[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg]'

    small_w = target_w // 4
    small_h = target_h // 4
    fc = (
        f'[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,'
        f'crop={target_w}:{target_h},'
        f'scale={small_w}:{small_h},boxblur={blur}:1,scale={target_w}:{target_h}[blurred];'
        f'{fg};'
        f'[blurred][fg]overlay=(W-w)/2:(H-h)/2[out]'
    )
    return [
        'ffmpeg', '-i', input_path,
        '-filter_complex', fc,
        '-map', '[out]', '-map', '0:a?',
        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
        '-progress', 'pipe:1', '-nostats',
        '-y', output_path,
    ]


def build_solid_cmd(input_path: str, output_path: str,
                    color: str = '000000', crop: dict = None,
                    target_w: int = 1080, target_h: int = 1920) -> list:
    """
    단색 배경 ffmpeg 커맨드를 반환한다.

    crop 딕트가 있으면 해당 영역을 잘라 축소 후 단색 패딩 처리한다.
    color: 6자리 hex (# 없이). 예) '000000', 'ffffff', '1a1a2e'
    """
    color = color.lstrip('#')
    crop_filter = ''
    if crop:
        cx, cy = int(crop['x']), int(crop['y'])
        cw = int(crop['w']) & ~1
        ch = int(crop['h']) & ~1
        crop_filter = f'crop={cw}:{ch}:{cx}:{cy},'
    vf = (
        f'{crop_filter}'
        f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,'
        f'pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=0x{color}'
    )
    return [
        'ffmpeg', '-i', input_path,
        '-vf', vf,
        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
        '-progress', 'pipe:1', '-nostats',
        '-y', output_path,
    ]


def make_preview(input_path: str, output_path: str,
                 bg_mode: str = 'none', crop: dict = None,
                 blur: int = 20, color: str = '000000',
                 target_w: int = 1080, target_h: int = 1920) -> None:
    """
    영상의 첫 프레임 1장을 추출해 지정 배경 모드로 처리한 JPEG를 생성한다.

    bg_mode: 'none'(크롭만) | 'blur'(블러 배경) | 'solid'(단색 배경)
    crop: 선택 영역 딕트 {x, y, w, h} — None이면 전체 영상
    """
    if bg_mode == 'blur':
        if crop:
            cx, cy = int(crop['x']), int(crop['y'])
            cw = int(crop['w']) & ~1
            ch = int(crop['h']) & ~1
            fg = (f'[0:v]crop={cw}:{ch}:{cx}:{cy},'
                  f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg]')
        else:
            fg = f'[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg]'
        small_w = target_w // 4
        small_h = target_h // 4
        fc = (
            f'[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,'
            f'crop={target_w}:{target_h},'
            f'scale={small_w}:{small_h},boxblur={blur}:1,scale={target_w}:{target_h}[blurred];'
            f'{fg};'
            f'[blurred][fg]overlay=(W-w)/2:(H-h)/2[out]'
        )
        cmd = [
            'ffmpeg', '-i', input_path,
            '-frames:v', '1',
            '-filter_complex', fc,
            '-map', '[out]',
            '-y', output_path,
        ]
    elif bg_mode == 'solid':
        color = color.lstrip('#')
        crop_filter = ''
        if crop:
            cx, cy = int(crop['x']), int(crop['y'])
            cw = int(crop['w']) & ~1
            ch = int(crop['h']) & ~1
            crop_filter = f'crop={cw}:{ch}:{cx}:{cy},'
        vf = (
            f'{crop_filter}'
            f'scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,'
            f'pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=0x{color}'
        )
        cmd = [
            'ffmpeg', '-i', input_path,
            '-frames:v', '1',
            '-vf', vf,
            '-y', output_path,
        ]
    else:  # 'none' — 크롭 영역만 미리보기
        if crop:
            x, y = int(crop['x']), int(crop['y'])
            w = int(crop['w']) & ~1
            h = int(crop['h']) & ~1
            cmd = [
                'ffmpeg', '-i', input_path,
                '-frames:v', '1',
                '-vf', f'crop={w}:{h}:{x}:{y}',
                '-y', output_path,
            ]
        else:
            cmd = ['ffmpeg', '-i', input_path, '-frames:v', '1', '-y', output_path]
    _run(cmd)


def _run(cmd: list) -> None:
    """ffmpeg/ffprobe 명령을 실행하고 오류 발생 시 예외를 던집니다."""
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        # ffmpeg 오류 메시지에서 마지막 10줄만 추출해서 읽기 쉽게 합니다
        error_lines = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(error_lines))

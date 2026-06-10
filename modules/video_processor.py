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


def _run(cmd: list) -> None:
    """ffmpeg/ffprobe 명령을 실행하고 오류 발생 시 예외를 던집니다."""
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        # ffmpeg 오류 메시지에서 마지막 10줄만 추출해서 읽기 쉽게 합니다
        error_lines = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(error_lines))

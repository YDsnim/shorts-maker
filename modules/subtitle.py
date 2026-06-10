# =====================================================
# modules/subtitle.py
# 자막 생성 및 영상에 삽입하는 모듈
# - 텍스트 → SRT 파일 자동 생성
# - ffmpeg로 자막을 영상에 굽기 (하드코딩)
# =====================================================

import os
import uuid
import subprocess
import tempfile


def create_srt_file(text: str, video_duration: float) -> str:
    """
    텍스트를 SRT 자막 파일로 변환합니다.
    줄바꿈을 기준으로 자막을 나누고,
    영상 길이에 맞춰 자막 시간을 균등 배분합니다.

    반환값: 생성된 .srt 파일 경로 (사용 후 삭제 필요)
    """
    # 빈 줄을 제거하고 자막 목록 만들기
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    if not lines:
        lines = [text.strip()]  # 줄바꿈이 없으면 전체를 하나의 자막으로

    # 각 자막이 표시될 시간 계산
    time_per_line = video_duration / len(lines)
    # 최소 1초, 최대 5초로 제한
    time_per_line = max(1.0, min(time_per_line, 5.0))

    srt_path = os.path.join(tempfile.gettempdir(), f'sub_{uuid.uuid4().hex}.srt')

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, line in enumerate(lines):
            start_sec = i * time_per_line
            end_sec = start_sec + time_per_line

            # SRT 형식: HH:MM:SS,mmm
            f.write(f"{i + 1}\n")
            f.write(f"{_sec_to_srt(start_sec)} --> {_sec_to_srt(end_sec)}\n")
            f.write(f"{line}\n\n")

    return srt_path


def burn_subtitles(video_path: str, srt_path: str, output_path: str) -> None:
    """
    SRT 자막을 영상에 직접 굽습니다 (하드코딩 방식).
    자막이 영상 픽셀에 합쳐지므로 어디서나 잘 보입니다.

    Windows에서는 경로에 콜론(:)이 있어 ffmpeg가 오해할 수 있으니
    특별히 처리합니다.
    """
    # Windows 경로를 ffmpeg가 읽을 수 있는 형식으로 변환
    safe_path = srt_path.replace('\\', '/').replace(':', '\\:')

    # 자막 스타일 (숏츠에 최적화된 굵고 큰 글씨, 화면 하단 중앙)
    style = (
        "FontName=Arial,"
        "FontSize=18,"
        "Bold=1,"
        "PrimaryColour=&H00FFFFFF,"   # 흰색 글자
        "OutlineColour=&H00000000,"   # 검정 외곽선
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"                # 하단 중앙
        "MarginV=60"                  # 아래쪽 여백
    )

    cmd = [
        'ffmpeg', '-i', video_path,
        '-vf', f"subtitles='{safe_path}':force_style='{style}'",
        '-c:a', 'copy',
        '-y', output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        error_lines = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(error_lines))


def _sec_to_srt(seconds: float) -> str:
    """초를 SRT 타임코드 형식(HH:MM:SS,mmm)으로 변환합니다."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

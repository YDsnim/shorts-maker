# =====================================================
# auto_pipeline/assemble.py
# 음성 + 배경 영상 + Whisper 자막을 조합해 최종 숏츠를 만듭니다.
#
# 처리 단계:
#   1. 배경 영상을 음성 길이에 맞게 9:16으로 트리밍
#   2. 배경에 TTS 음성 합치기
#   3. Whisper로 음성에서 자막 타이밍 추출
#   4. SRT 자막 파일 생성
#   5. 자막을 영상에 굽기 (하드코딩)
# =====================================================

import os
import subprocess
import sys
import tempfile

# 부모 폴더의 모듈을 공유합니다
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from modules.subtitle import burn_subtitles


def assemble_stages(voice_path: str, bg_path: str,
                    output_path: str, duration: float,
                    jobs: dict, job_id: str) -> None:
    """
    배경 영상 트리밍 → 음성 합치기 → 자막 생성 → 자막 소각 단계를 순서대로 실행합니다.

    voice_path:   TTS mp3 파일 경로
    bg_path:      Pexels 배경 영상 파일 경로
    output_path:  최종 결과 파일 저장 경로
    duration:     음성 길이(초) — 배경 영상 트리밍 기준
    jobs:         SSE 진행률 공유 딕셔너리 (_jobs in app.py)
    job_id:       현재 작업 ID
    """
    tmp = tempfile.mkdtemp()

    try:
        # ── 1. 배경 영상 트리밍 + 9:16 크롭 ──────────────
        jobs[job_id].update({'pct': 42, 'msg': '🎬 배경 영상 자르는 중...'})
        trimmed = os.path.join(tmp, 'trimmed.mp4')
        _run_ffmpeg([
            'ffmpeg', '-stream_loop', '-1', '-i', bg_path,
            '-t', str(duration),
            # 9:16(1080×1920)으로 크롭: 먼저 충분히 키운 뒤 정확히 잘라냄
            '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,'
                   'crop=1080:1920',
            '-c:v', 'libx264', '-an',   # 오디오 없이 영상만
            '-y', trimmed,
        ])

        # ── 2. TTS 음성 합치기 ────────────────────────────
        jobs[job_id].update({'pct': 55, 'msg': '🔊 음성 합치는 중...'})
        merged = os.path.join(tmp, 'merged.mp4')
        _run_ffmpeg([
            'ffmpeg',
            '-i', trimmed,
            '-i', voice_path,
            '-map', '0:v:0',    # 배경 영상 스트림
            '-map', '1:a:0',    # TTS 오디오 스트림
            '-c:v', 'copy', '-c:a', 'aac',
            '-shortest',        # 둘 중 짧은 쪽 기준으로 종료
            '-y', merged,
        ])

        # ── 3. Whisper로 자막 타이밍 생성 ────────────────
        jobs[job_id].update({'pct': 65, 'msg': '📝 자막 타이밍 생성 중 (Whisper)...'})
        srt_path = os.path.join(tmp, 'subtitles.srt')
        _generate_subtitles(voice_path, srt_path)

        # ── 4. 자막 소각 ──────────────────────────────────
        jobs[job_id].update({'pct': 88, 'msg': '✍️ 자막 영상에 굽는 중...'})
        burn_subtitles(merged, srt_path, output_path)

        jobs[job_id].update({'pct': 100, 'done': True})

    except Exception as e:
        jobs[job_id].update({'done': True, 'error': str(e)})
        raise
    finally:
        # 성공·실패 모두 임시 파일 정리
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel('medium', device='cuda', compute_type='float32')
    return _whisper_model


def _generate_subtitles(voice_path: str, srt_path: str) -> None:
    """
    faster-whisper medium 모델로 음성 파일의 단어 타이밍을 추출하고 SRT를 저장합니다.
    voice_path: TTS로 만든 mp3 파일 (한국어)
    srt_path:   저장할 SRT 파일 경로
    """
    model = _get_whisper_model()
    segments, _info = model.transcribe(voice_path, language='ko')
    _write_srt(list(segments), srt_path)


def _write_srt(segments: list, srt_path: str) -> None:
    """Whisper 세그먼트 목록을 SRT 파일로 저장합니다."""
    def sec_to_srt(s: float) -> str:
        h  = int(s // 3600)
        m  = int((s % 3600) // 60)
        sc = int(s % 60)
        ms = int((s % 1) * 1000)
        return f"{h:02d}:{m:02d}:{sc:02d},{ms:03d}"

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{sec_to_srt(seg.start)} --> {sec_to_srt(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")


def _run_ffmpeg(cmd: list) -> None:
    """ffmpeg 명령을 실행하고 오류 시 예외를 던집니다."""
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode != 0:
        err = result.stderr.strip().splitlines()[-10:]
        raise RuntimeError('\n'.join(err))

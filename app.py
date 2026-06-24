# =====================================================
# app.py — 숏츠 메이커 Flask 메인 앱
#
# 역할:
#   · 브라우저와 서버 사이의 모든 HTTP 통신을 담당
#   · 파일 업로드, 크롭/블러/단색 처리, YouTube 다운로드,
#     서버 프리뷰, STT, 다운로드 등 각 기능별 엔드포인트 정의
#   · 영상 실제 처리는 modules/video_processor.py 에 위임
#   · 장시간 작업(ffmpeg, Whisper)은 백그라운드 스레드로 실행하고
#     SSE(Server-Sent Events)로 진행률을 브라우저에 실시간 전송
#
# 실행: python app.py  →  http://localhost:5000
# =====================================================

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import uuid
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    filename='error.log',
    level=logging.ERROR,
    format='%(asctime)s\n%(message)s\n' + '-' * 60,
    encoding='utf-8',
)

def log_error(e: Exception) -> None:
    logging.error(traceback.format_exc())
    print(traceback.format_exc())

from flask import (Flask, render_template, request, jsonify,
                   send_file, Response, stream_with_context)
from werkzeug.utils import secure_filename

import config
import modules.video_processor as vp

app = Flask(__name__)
# Flask가 허용하는 최대 업로드 크기를 config에서 읽어 설정
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# 앱 시작 시 저장 폴더가 없으면 미리 만들어둔다
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)

# ── 전역 상태 변수 ────────────────────────────────────
# 마지막으로 파일 정리를 실행한 시각
_last_cleanup  = 0.0

# Whisper 모델 캐시: 처음 요청 시 로드한 뒤 메모리에 유지
_whisper_model = None
_whisper_lock  = threading.Lock()   # 동시 추론 충돌 방지

# 백그라운드 작업 레지스트리
# job_id → { pct, done, error, result, original, srt, msg }
_jobs: dict = {}


# ─────────────────────────────────────────────────────
# 헬퍼 함수
# ─────────────────────────────────────────────────────

def safe_filename(name: str) -> bool:
    """
    파일명에 경로 조작 문자( / \\ ..)가 있는지 검사한다.
    공격자가 '../etc/passwd' 같은 경로를 보내는 경로 순회 공격을 막는다.
    """
    return os.sep not in name and '/' not in name and '..' not in name


def sanitize_base(name: str) -> str:
    """
    파일명 베이스 정리: 확장자 제거 → OS 금지 문자 제거 → 공백→언더스코어 → 80자 제한
    결과가 빈 문자열이면 'video' 반환.
    """
    base = name.rsplit('.', 1)[0] if '.' in name else name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', base)
    base = base.strip().replace(' ', '_')
    return base[:80] or 'video'


def make_upload_name(base: str, ext: str, suffix: str = '') -> str:
    """날짜_원본명[_suffix].ext 형식으로 업로드 파일명을 생성한다. 충돌 시 카운터 추가."""
    date_str = datetime.now().strftime('%y%m%d_%H%M%S')
    stem     = f'{date_str}_{base}' + (f'_{suffix}' if suffix else '')
    filename = f'{stem}.{ext}'
    n = 2
    while os.path.exists(os.path.join(config.UPLOAD_FOLDER, filename)):
        filename = f'{stem}_{n}.{ext}'
        n += 1
    return filename


def make_output_name(base: str, mode: str = 'crop') -> str:
    """날짜_원본명_모드_N.mp4 형식. 같은 이름이 이미 있으면 N을 올린다."""
    date_str = datetime.now().strftime('%y%m%d_%H%M%S')
    n = 1
    while True:
        name = f'{date_str}_{base}_{mode}_{n}.mp4'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def make_srt_name(base: str) -> str:
    """원본명_자막.srt 형식, 중복 시 _N 추가."""
    name = f'{base}_자막.srt'
    if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
        return name
    n = 2
    while True:
        name = f'{base}_자막_{n}.srt'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def cleanup_old_files():
    """
    OUTPUT_TTL_SECONDS 이상 된 파일을 uploads/·output/ 에서 정리한다.
    마지막 실행으로부터 TTL이 지나지 않았으면 바로 반환 (매 요청마다 삭제하지 않음).
    """
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < config.OUTPUT_TTL_SECONDS:
        return
    _last_cleanup = now
    cutoff = now - config.OUTPUT_TTL_SECONDS
    for folder in (config.OUTPUT_FOLDER, config.UPLOAD_FOLDER):
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass

    # 완료된 지 60초 이상 지난 _jobs 항목 정리 (메모리 누수 방지)
    jobs_cutoff = now - 60
    stale = [jid for jid, j in _jobs.items()
             if j.get('done') and j.get('finished_at', 0) < jobs_cutoff]
    for jid in stale:
        _jobs.pop(jid, None)


def get_whisper_model():
    """
    faster-whisper small 모델을 반환한다 (처음 한 번만 로드, 이후 캐시 재사용).
    첫 실행 시 모델을 다운로드하고 메모리에 로드하는 데 수 초가 걸린다.
    """
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        try:
            _whisper_model = WhisperModel('large-v3-turbo', device='cuda', compute_type='float16')
        except Exception:
            _whisper_model = WhisperModel('large-v3-turbo', device='cpu', compute_type='int8')
    return _whisper_model


def allowed_file(filename: str) -> bool:
    """파일 확장자가 허용 목록에 있는지 확인한다."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in config.ALLOWED_EXTENSIONS


def _sec_to_srt_time(seconds: float) -> str:
    """초 → SRT 타임스탬프 형식 (HH:MM:SS,mmm)."""
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = (int(seconds) // 60) % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(segments) -> str:
    """faster-whisper 세그먼트 목록을 SRT 파일 문자열로 변환한다."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _sec_to_srt_time(seg.start)
        end   = _sec_to_srt_time(seg.end)
        lines.append(f"{i}\n{start} --> {end}\n{seg.text.strip()}")
    return '\n\n'.join(lines) + '\n'


# ─────────────────────────────────────────────────────
# 백그라운드 작업 (SSE 진행률 연동)
# ─────────────────────────────────────────────────────

def _run_job_thread(cmd: list, job_id: str, duration: float,
                    input_path: str, orig_filename: str) -> None:
    """
    ffmpeg를 백그라운드 스레드에서 실행하며 진행률을 _jobs에 업데이트한다.

    pipe:1 대신 임시 파일로 진행률을 수신해 Windows 파이프 버퍼링 문제를 우회한다.
    stderr도 임시 파일에 기록해 파이프 버퍼(4KB) 데드락을 방지한다.
    ffmpeg 종료 후 임시 파일을 읽어 에러 내용을 추출한다.
    """
    progress_file = os.path.join(config.UPLOAD_FOLDER, f'prog_{job_id}.txt')
    stderr_file   = os.path.join(config.UPLOAD_FOLDER, f'err_{job_id}.txt')
    cmd = [progress_file if p == 'pipe:1' else p for p in cmd]

    try:
        # stderr를 파이프 대신 파일로 받아 데드락 방지
        sf = open(stderr_file, 'w', encoding='utf-8', errors='replace')
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=sf)
        finally:
            sf.close()  # 부모 핸들은 즉시 닫아도 자식(ffmpeg)은 계속 쓸 수 있음

        _jobs[job_id]['msg'] = '변환 중...'

        while proc.poll() is None:
            try:
                if os.path.exists(progress_file):
                    with open(progress_file, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    for line in reversed(content.splitlines()):
                        if line.startswith('out_time_ms='):
                            val = line.split('=')[1].strip()
                            if val not in ('', 'N/A') and duration > 0:
                                pct = min(int(int(val) / 1_000_000 / duration * 100), 99)
                                _jobs[job_id]['pct'] = pct
                            break
            except (ValueError, OSError):
                pass
            time.sleep(0.5)

        proc.wait()

        if proc.returncode == 0:
            _jobs[job_id].update({'pct': 100, 'done': True, 'finished_at': time.time(), 'msg': '완료!'})
        else:
            try:
                with open(stderr_file, 'r', encoding='utf-8', errors='replace') as f:
                    err = f.read()[-300:]
            except OSError:
                err = ''
            _jobs[job_id].update({'done': True, 'finished_at': time.time(), 'error': err or '처리 중 오류 발생'})

    except Exception as e:
        log_error(e)
        if job_id in _jobs:
            _jobs[job_id].update({'done': True, 'finished_at': time.time(), 'error': str(e)})
    finally:
        for p in (progress_file, stderr_file):
            try:
                os.remove(p)
            except OSError:
                pass


# ─────────────────────────────────────────────────────
# 훅: 모든 요청 전에 파일 정리
# ─────────────────────────────────────────────────────

@app.before_request
def periodic_cleanup():
    """매 요청마다 호출되지만, 실제 삭제는 TTL 주기(1시간)에 한 번만 일어난다."""
    cleanup_old_files()


# ─────────────────────────────────────────────────────
# 라우트
# ─────────────────────────────────────────────────────

@app.route('/')
def index():
    """메인 페이지."""
    return render_template('index.html')


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/uploads/<filename>')
def serve_upload(filename: str):
    """업로드된 원본 영상을 스트리밍한다 (크롭 UI 미리보기용)."""
    if not safe_filename(filename):
        return '', 404
    path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return '', 404
    return send_file(path, conditional=True, etag=True, max_age=0)


@app.route('/upload', methods=['POST'])
def upload():
    """
    영상 파일을 uploads/ 에 저장한다.
    파일명을 UUID로 바꿔 중복 충돌을 방지하고,
    원본 파일명 베이스(original_base)는 응답에 포함해 다운로드명에 활용한다.
    """
    if 'video' not in request.files:
        return jsonify({'ok': False, 'error': '파일이 없습니다.'}), 400

    file = request.files['video']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'ok': False, 'error': f'지원 형식: {", ".join(config.ALLOWED_EXTENSIONS)}'}), 400

    ext           = file.filename.rsplit('.', 1)[-1].lower()
    original_base = sanitize_base(file.filename)
    filename      = make_upload_name(original_base, ext)
    save_path     = os.path.join(config.UPLOAD_FOLDER, filename)
    file.save(save_path)

    try:
        info = vp.get_video_info(save_path)
    except Exception:
        info = {}

    return jsonify({'ok': True, 'filename': filename, 'original_base': original_base, 'info': info})


@app.route('/preview', methods=['POST'])
def preview():
    """
    서버 프리뷰: 첫 프레임을 선택한 모드로 처리해 JPEG로 반환한다.

    실제 영상 처리와 완전히 동일한 ffmpeg 필터를 사용하므로
    최종 결과물과 정확히 같은 화면을 미리 볼 수 있다.

    캐싱: 같은 파일 + 같은 파라미터 조합이면 이전에 생성한 JPEG를 재사용한다.
    """
    data     = request.get_json(force=True)
    filename = data.get('filename', '')
    bg_mode  = data.get('bg_mode', data.get('mode', 'none'))
    crop     = data.get('crop')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    # 파일 위치 탐색: output/ 우선, 없으면 uploads/
    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    seek_time = float(data.get('seek_time', 0) or 0)

    # 캐시 키: bg_mode + crop 좌표 + 파라미터 + seek_time 조합
    c = crop or {}
    crop_key = f"{int(c.get('x',0))}_{int(c.get('y',0))}_{int(c.get('w',0))}_{int(c.get('h',0))}"
    seek_key = f"{seek_time:.3f}"
    if bg_mode == 'blur':
        key = f"blur_{int(data.get('blur', 20))}_{crop_key}_{seek_key}"
    elif bg_mode == 'solid':
        key = f"solid_{data.get('color', '000000').lstrip('#')}_{crop_key}_{seek_key}"
    else:
        key = f"none_{crop_key}_{seek_key}"

    base         = os.path.splitext(filename)[0]
    preview_name = f"prev_{base}_{key}.jpg"
    preview_path = os.path.join(config.OUTPUT_FOLDER, preview_name)

    if not os.path.exists(preview_path):
        try:
            vp.make_preview(
                path, preview_path,
                bg_mode=bg_mode,
                crop=crop,
                blur=int(data.get('blur', 20)),
                color=data.get('color', '000000'),
                seek_time=seek_time,
            )
        except Exception as e:
            log_error(e)
            return jsonify({'ok': False, 'error': str(e)}), 500

    return send_file(preview_path, mimetype='image/jpeg')


@app.route('/process', methods=['POST'])
def process():
    """
    크롭/블러/단색 처리를 백그라운드 스레드로 시작하고 job_id를 즉시 반환한다.
    브라우저는 job_id로 /progress/<job_id> SSE를 구독해 진행률을 받는다.

    mode: 'crop' | 'blur' | 'solid'
    """
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')
    bg_mode       = data.get('bg_mode', data.get('mode', 'none'))
    crop          = data.get('crop')
    blur_level    = int(data.get('blur', 20))
    color         = (data.get('color') or '000000').lstrip('#')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    input_path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(input_path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    if bg_mode == 'none' and not crop:
        return jsonify({'ok': False, 'error': '크롭 정보가 없습니다.'}), 400

    # crop이 있어도 w/h가 0이면 ffmpeg 오류 → 사전 차단
    if crop and (int(crop.get('w', 0)) <= 0 or int(crop.get('h', 0)) <= 0):
        return jsonify({'ok': False, 'error': '크롭 영역의 너비 또는 높이가 0입니다.'}), 400

    mode_label  = {'none': 'crop', 'blur': 'blur', 'solid': 'color'}.get(bg_mode, 'crop')
    result_name = make_output_name(original_base, mode_label)
    result_path = os.path.join(config.OUTPUT_FOLDER, result_name)

    try:
        duration = vp.get_video_info(input_path).get('duration', 0)

        if bg_mode == 'none':
            cmd = vp.build_crop_cmd(
                input_path, result_path,
                int(crop['x']), int(crop['y']),
                int(crop['w']), int(crop['h']),
            )
        elif bg_mode == 'blur':
            cmd = vp.build_blur_cmd(input_path, result_path, blur=blur_level, crop=crop)
        else:
            cmd = vp.build_solid_cmd(input_path, result_path, color=color, crop=crop)

        job_id = uuid.uuid4().hex[:8]
        _jobs[job_id] = {
            'pct': 0, 'done': False, 'error': None,
            'result': result_name, 'original': None, 'srt': None,
            'msg': '처리 시작 중...',
        }

        t = threading.Thread(
            target=_run_job_thread,
            args=(cmd, job_id, duration, input_path, filename),
            daemon=True,
        )
        t.start()

        return jsonify({'ok': True, 'job_id': job_id})

    except Exception as e:
        log_error(e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/progress/<job_id>')
def progress_stream(job_id: str):
    """
    SSE 엔드포인트: 백그라운드 작업 진행률을 0.3초 간격으로 스트리밍한다.

    클라이언트가 EventSource로 이 URL을 구독하면
    {'pct': 0~100, 'done': bool, 'msg': str} 형태의 JSON을 받는다.
    완료 시 'result', 'original', 'srt' 필드도 포함된다.
    최대 20분 후 타임아웃 메시지를 보내고 스트림을 닫는다.
    """
    def generate():
        deadline = time.time() + 1200
        while time.time() < deadline:
            job = _jobs.get(job_id)

            # 작업이 아직 _jobs에 등록되기 전일 수 있음 (race condition 방지)
            if job is None:
                yield f'data: {json.dumps({"pct": 0, "done": False})}\n\n'
                time.sleep(0.3)
                continue

            pct   = job.get('pct', 0)
            done  = job.get('done', False)
            error = job.get('error')
            msg   = job.get('msg', '')

            if error:
                yield f'data: {json.dumps({"pct": pct, "done": True, "error": error})}\n\n'
                _jobs.pop(job_id, None)
                return

            payload = {'pct': pct, 'done': done, 'msg': msg}
            if done:
                payload['result']   = job.get('result')
                payload['original'] = job.get('original')
                payload['srt']      = job.get('srt')
                payload['segments'] = job.get('segments')

            yield f'data: {json.dumps(payload)}\n\n'

            if done:
                _jobs.pop(job_id, None)
                return

            time.sleep(0.3)

        yield f'data: {json.dumps({"done": True, "error": "처리 시간 초과 (10분)"})}\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/fetch-youtube', methods=['POST'])
def fetch_youtube():
    """
    YouTube URL에서 영상을 다운로드해 uploads/ 에 저장한다.
    yt-dlp 로 최고 화질 mp4를 받아 UUID 파일명으로 저장한다.
    """
    data = request.get_json(force=True)
    url  = (data.get('url') or '').strip()

    if not url or not re.search(r'(youtube\.com|youtu\.be)', url):
        return jsonify({'ok': False, 'error': '유효하지 않은 YouTube URL'}), 400

    try:
        # 영상 제목 먼저 조회 (다운로드 없이)
        title_result = subprocess.run(
            ['yt-dlp', '--get-filename', '-o', '%(title)s', '--no-playlist', url],
            capture_output=True, text=True, timeout=30,
        )
        raw_title     = title_result.stdout.strip().split('\n')[0] or 'video'
        original_base = sanitize_base(raw_title)

        temp_name = make_upload_name(original_base, 'mp4', 'yt')
        temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

        subprocess.run(
            [
                'yt-dlp',
                # mp4+m4a 최고화질 조합 → ffmpeg 자동 병합
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '--no-playlist',
                '-o', temp_path,
                url,
            ],
            capture_output=True, text=True, timeout=300, check=True,
        )

        try:
            info = vp.get_video_info(temp_path)
        except Exception:
            info = {}

        return jsonify({'ok': True, 'filename': temp_name,
                        'original_base': original_base, 'info': info})

    except FileNotFoundError:
        return jsonify({'ok': False, 'error': 'yt-dlp가 설치되지 않았습니다.'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': '다운로드 시간 초과 (5분)'}), 500
    except subprocess.CalledProcessError as e:
        err = (e.stderr or '')[-300:]
        return jsonify({'ok': False, 'error': f'다운로드 실패: {err}'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/transcribe', methods=['POST'])
def transcribe():
    """
    영상에서 음성을 인식해 SRT 대본 파일을 생성한다.
    Whisper 처리는 백그라운드 스레드로 실행하고 SSE로 진행 단계를 알린다.
    """
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    # output/ 우선 탐색 (크롭 완료 후 원본이 이동됐을 수 있음)
    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        'pct': 0, 'done': False, 'error': None,
        'result': None, 'original': None, 'srt': None,
        'msg': '준비 중...',
    }

    _path = path
    _base = original_base

    def _run_transcribe():
        try:
            _jobs[job_id].update({'msg': '모델 준비 중... (1/3)', 'pct': 10})
            with _whisper_lock:
                model = get_whisper_model()
                _jobs[job_id].update({'msg': '음성 인식 중... (2/3)', 'pct': 30})
                segments, _ = model.transcribe(
                    _path, language='ko',
                    vad_filter=True,
                    vad_parameters={'min_silence_duration_ms': 300},
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    initial_prompt='안녕하세요.',
                )
                segments = list(segments)

            _jobs[job_id].update({'msg': 'SRT 저장 중... (3/3)', 'pct': 90})
            srt_name = make_srt_name(_base)
            srt_path = os.path.join(config.OUTPUT_FOLDER, srt_name)
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(_to_srt(segments))

            _jobs[job_id].update({'pct': 100, 'done': True, 'finished_at': time.time(), 'srt': srt_name, 'msg': '완료'})

        except ModuleNotFoundError:
            _jobs[job_id].update({'done': True, 'finished_at': time.time(),
                                  'error': 'faster-whisper가 설치되지 않았습니다. pip install faster-whisper'})
        except Exception as e:
            log_error(e)
            _jobs[job_id].update({'done': True, 'finished_at': time.time(), 'error': str(e)})

    threading.Thread(target=_run_transcribe, daemon=True).start()
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/download/<filename>')
def download(filename: str):
    """
    output/ 폴더의 파일을 브라우저로 다운로드한다.
    .mp4, .srt 등 확장자에 무관하게 처리한다.
    """
    if not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일 없음'}), 404

    return send_file(path, as_attachment=True, download_name=filename)


# ─────────────────────────────────────────────────────
# 영상 창작 파이프라인 라우트
# 주제 → 대본(Claude) → 음성(edge-tts) → 배경(Pexels) → 자막(Whisper) → 조립(ffmpeg)
# ─────────────────────────────────────────────────────

@app.route('/pipeline/check-config')
def pipeline_check_config():
    """
    파이프라인에 필요한 API 키 설정 여부를 확인한다.
    프론트엔드가 시작 시 호출해 경고를 표시하는 데 사용한다.
    """
    try:
        import auto_pipeline.config as pc
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500



@app.route('/pipeline/upload-source', methods=['POST'])
def pipeline_upload_source():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'ok': False, 'error': '파일 없음'}), 400
    ext      = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else 'mp4'
    base     = sanitize_base(f.filename)
    filename = make_upload_name(base, ext, 'src')
    save_path = os.path.join(config.UPLOAD_FOLDER, filename)
    f.save(save_path)
    import modules.video_processor as vp
    info = vp.get_video_info(save_path)
    return jsonify({'ok': True, 'filename': filename, 'duration': info.get('duration', 0)})


@app.route('/pipeline/template-preview', methods=['POST'])
def pipeline_template_preview():
    data          = request.get_json(silent=True) or {}
    filename      = data.get('filename', '')
    tpl_key       = data.get('template', 'namnam')
    title         = data.get('title', '')
    positions     = data.get('positions',     {})
    styles        = data.get('styles',        {})
    seek_time     = max(0.0, float(data.get('seek_time', 3)))
    custom_layers = data.get('custom_layers', [])

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    video_path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(video_path):
        return jsonify({'ok': False, 'error': '파일 없음'}), 404

    try:
        from modules.banner import generate_template_preview
        out_name = f'tpl_preview_{uuid.uuid4().hex[:8]}.jpg'
        out_path = os.path.join(config.OUTPUT_FOLDER, out_name)
        generate_template_preview(video_path, out_path, tpl_key, title,
                                  positions=positions, styles=styles,
                                  seek_time=seek_time,
                                  custom_layers=custom_layers)
        return jsonify({'ok': True, 'preview_url': f'/download/{out_name}'})
    except Exception as e:
        log_error(e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/pipeline/generate-script', methods=['POST'])
def pipeline_generate_script():
    """
    Claude API로 숏츠 대본과 배경영상 검색 키워드를 생성한다.
    비용: claude-haiku 기준 편당 약 1~2원.
    """
    data  = request.get_json(force=True)
    topic = (data.get('topic') or '').strip()

    if not topic:
        return jsonify({'ok': False, 'error': '주제를 입력해주세요.'}), 400

    try:
        import auto_pipeline.config as pc
        from auto_pipeline.generate_script import generate_script

        if not pc.CLAUDE_API_KEY:
            return jsonify({
                'ok': False,
                'error': 'CLAUDE_API_KEY 환경변수가 설정되지 않았습니다.\n'
                         'export CLAUDE_API_KEY=sk-ant-... 후 서버를 재시작하세요.',
            }), 400

        result = generate_script(topic, pc.CLAUDE_API_KEY, pc.CLAUDE_MODEL)
        return jsonify({
            'ok':       True,
            'titles':   result.get('titles', []),
            'script':   result.get('script', ''),
            'keywords': result.get('keywords', []),
            'scenes':   result.get('scenes', []),
        })

    except Exception as e:
        log_error(e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/pipeline/run', methods=['POST'])
def pipeline_run():
    """
    대본 승인 후 전 과정(음성·배경·자막·조립)을 백그라운드로 실행한다.
    완료까지 2~5분 소요. SSE /progress/<job_id> 로 진행률을 받는다.
    """
    data               = request.get_json(force=True)
    script             = (data.get('script') or '').strip()
    topic              = (data.get('topic') or 'shorts').strip()
    template           = (data.get('template') or 'namnam').strip()
    source_filename    = (data.get('source_filename') or '').strip()
    use_tts            = bool(data.get('use_tts', True))
    use_subtitle       = bool(data.get('use_subtitle', True))
    positions          = data.get('positions')    or {}
    styles             = data.get('styles')       or {}
    custom_layers      = data.get('custom_layers') or []
    tts_voice          = (data.get('tts_voice') or 'ko-KR-Neural2-C').strip()
    tts_speed          = max(0.25, min(4.0, float(data.get('tts_speed') or 1.0)))
    if not script and use_tts:
        return jsonify({'ok': False, 'error': '대본이 없습니다. (TTS 끄면 대본 없어도 됩니다)'}), 400
    if not source_filename:
        return jsonify({'ok': False, 'error': '메인 소스 영상을 업로드해주세요.'}), 400
    if not safe_filename(source_filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명입니다.'}), 400

    source_path = os.path.join(config.UPLOAD_FOLDER, source_filename)
    if not os.path.exists(source_path):
        return jsonify({'ok': False, 'error': '소스 영상 파일을 찾을 수 없습니다.'}), 400

    try:
        import auto_pipeline.config as pc
    except Exception as e:
        return jsonify({'ok': False, 'error': f'파이프라인 설정 오류: {e}'}), 500

    # 결과 파일명 생성: 숏츠_{주제}_{N}.mp4
    original_base = sanitize_base(topic)
    result_name   = _make_pipeline_name(original_base)
    result_path   = os.path.join(config.OUTPUT_FOLDER, result_name)

    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        'pct': 0, 'done': False, 'error': None,
        'result': result_name, 'original': None, 'srt': None,
        'msg': '준비 중...',
    }

    def _run():

        tmp        = tempfile.mkdtemp()
        voice_path = os.path.join(tmp, 'voice.mp3')

        try:
            from auto_pipeline.generate_voice import generate_voice, get_audio_duration

            if use_tts:
                # ── 1a. TTS 음성 생성 ─────────────────────
                _jobs[job_id].update({'pct': 10, 'msg': '🔊 TTS 음성 생성 중...'})
                generate_voice(script, voice_path, speaker=tts_voice, speed=tts_speed)
            else:
                # ── 1b. 소스 영상에서 오디오 추출 ──────────
                _jobs[job_id].update({'pct': 10, 'msg': '🔊 원본 오디오 추출 중...'})
                subprocess.run([
                    'ffmpeg', '-i', source_path, '-vn',
                    '-acodec', 'libmp3lame', '-q:a', '2',
                    '-y', voice_path,
                ], check=True, capture_output=True)

            duration = get_audio_duration(voice_path)
            if duration <= 0:
                raise RuntimeError("오디오 추출에 실패했습니다.")

            # ── 2. 소스 영상 → 배경으로 사용 ─────────────
            _jobs[job_id].update({'pct': 30, 'msg': '🎬 소스 영상 준비 중...'})
            bg_paths = [source_path]

            # ── 3~5. 조립 ─────────────────────────────────
            _jobs[job_id].update({'pct': 42, 'msg': '⚙️ 영상 조립 중...'})
            from auto_pipeline.assemble import assemble_stages
            srt_name = result_name.replace('.mp4', '.srt')
            srt_path = os.path.join(config.OUTPUT_FOLDER, srt_name)
            assemble_stages(voice_path, bg_paths, result_path, duration, _jobs, job_id,
                            srt_save_path=srt_path, scenes=[], title=topic, template=template,
                            use_tts=use_tts, overlay_specs=[],
                            positions=positions, styles=styles,
                            use_subtitle=use_subtitle, custom_layers=custom_layers)
            # srt·done 은 assemble_stages 내부에서 원자적으로 설정됨

        except Exception as e:
            log_error(e)
            _jobs[job_id].update({'done': True, 'finished_at': time.time(), 'error': str(e)})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/proofread', methods=['POST'])
def proofread():
    """
    Claude API로 대본 맞춤법·오타를 교정한다.
    CLAUDE_API_KEY + ANTHROPIC_BASE_URL(aiprimetech 등) 환경변수를 사용한다.
    """
    data = request.get_json(force=True)
    text = (data.get('text') or '').strip()

    if not text:
        return jsonify({'ok': False, 'error': '대본을 입력해주세요.'}), 400

    try:
        import auto_pipeline.config as pc
    except Exception as e:
        return jsonify({'ok': False, 'error': f'설정 오류: {e}'}), 500

    if not pc.CLAUDE_API_KEY:
        return jsonify({
            'ok': False,
            'error': 'CLAUDE_API_KEY 환경변수가 설정되지 않았습니다.',
        }), 400

    try:
        import anthropic
        base_url = os.environ.get('ANTHROPIC_BASE_URL')
        client   = anthropic.Anthropic(
            api_key=pc.CLAUDE_API_KEY,
            **({"base_url": base_url} if base_url else {}),
        )

        prompt = (
            "다음 한국어 대본의 맞춤법과 오타를 교정해주세요.\n\n"
            "규칙:\n"
            "- 맞춤법 오류, 오타, 띄어쓰기 오류만 수정하세요\n"
            "- 문장 의미·스타일·구어체는 그대로 유지하세요\n"
            "- 아래 JSON 형식으로만 답하세요\n\n"
            '{"corrected":"교정된 전체 대본","changes":["변경사항1","변경사항2"]}\n\n'
            f"대본:\n{text}"
        )

        msg = client.messages.create(
            model=pc.CLAUDE_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        # 텍스트 블록 탐색 (tool_use 블록이 섞여 있을 수 있음)
        raw = next(
            (block.text for block in msg.content if hasattr(block, 'text')),
            '',
        ).strip()

        if not raw:
            return jsonify({'ok': False, 'error': 'Claude 응답이 비어 있습니다.'}), 500

        # JSON 블록만 추출 (```json ... ``` 래핑 대응)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        try:
            result = json.loads(match.group() if match else raw)
            return jsonify({
                'ok':        True,
                'corrected': result.get('corrected', ''),
                'changes':   result.get('changes', []),
            })
        except json.JSONDecodeError:
            return jsonify({'ok': True, 'corrected': raw, 'changes': []})
    except Exception as e:
        log_error(e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/tts/generate', methods=['POST'])
def tts_generate():
    """텍스트 → edge-tts mp3 파일 생성"""
    data  = request.get_json(force=True) or {}
    text  = (data.get('text') or '').strip()
    voice = (data.get('voice') or 'ko-KR-Neural2-C').strip()
    speed = max(0.25, min(4.0, float(data.get('speed') or 1.0)))

    if not text:
        return jsonify({'ok': False, 'error': '텍스트를 입력해주세요.'}), 400

    try:
        from auto_pipeline.generate_voice import generate_voice
        out_name = f'tts_{uuid.uuid4().hex[:8]}.mp3'
        out_path = os.path.join(config.OUTPUT_FOLDER, out_name)
        generate_voice(text, out_path, speaker=voice, speed=speed)
        return jsonify({'ok': True, 'audio_url': f'/download/{out_name}', 'filename': out_name})
    except Exception as e:
        log_error(e)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/subtitle/analyze', methods=['POST'])
def subtitle_analyze():
    """영상 오디오를 Whisper로 분석해 편집 가능한 세그먼트 JSON을 반환한다."""
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {
        'pct': 0, 'done': False, 'error': None,
        'result': None, 'original': None, 'srt': None,
        'segments': None, 'msg': '준비 중...',
    }

    _path = path

    def _run():
        try:
            _jobs[job_id].update({'msg': '모델 준비 중... (1/2)', 'pct': 10})
            with _whisper_lock:
                model = get_whisper_model()
                _jobs[job_id].update({'msg': '음성 인식 중... (2/2)', 'pct': 30})
                segments, _ = model.transcribe(
                    _path, language='ko',
                    vad_filter=True,
                    vad_parameters={'min_silence_duration_ms': 300},
                    condition_on_previous_text=False,
                    no_speech_threshold=0.6,
                    initial_prompt='안녕하세요.',
                )
                segs = [
                    {'id': i, 'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip()}
                    for i, s in enumerate(list(segments), 1)
                ]
            _jobs[job_id].update({
                'pct': 100, 'done': True,
                'finished_at': time.time(),
                'segments': segs,
                'msg': '완료',
            })
        except ModuleNotFoundError:
            _jobs[job_id].update({'done': True, 'finished_at': time.time(),
                                  'error': 'faster-whisper가 설치되지 않았습니다.'})
        except Exception as e:
            log_error(e)
            _jobs[job_id].update({'done': True, 'finished_at': time.time(), 'error': str(e)})

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'job_id': job_id})


@app.route('/subtitle/export-srt', methods=['POST'])
def subtitle_export_srt():
    """클라이언트에서 편집한 세그먼트를 SRT 파일로 저장하고 다운로드 URL을 반환한다."""
    data          = request.get_json(force=True)
    segments      = data.get('segments', [])
    filename_base = sanitize_base(data.get('filename_base', '') or 'subtitle')

    if not segments:
        return jsonify({'ok': False, 'error': '자막 데이터가 없습니다.'}), 400

    lines = []
    for seg in segments:
        start = _sec_to_srt_time(float(seg.get('start', 0)))
        end   = _sec_to_srt_time(float(seg.get('end',   0)))
        text  = (seg.get('text') or '').strip()
        if text:
            lines.append(f"{seg['id']}\n{start} --> {end}\n{text}")

    srt_content = '\n\n'.join(lines) + '\n'
    srt_name    = make_srt_name(filename_base)
    srt_path    = os.path.join(config.OUTPUT_FOLDER, srt_name)
    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)

    return jsonify({'ok': True, 'srt': srt_name})


def _make_pipeline_name(base: str) -> str:
    """주제앞8자_날짜_N.mp4 형식, output/ 에 이미 있으면 N을 올린다."""
    from datetime import date
    today  = date.today().strftime('%y%m%d')
    short  = base[:8] if base else 'shorts'
    n = 1
    while True:
        name = f'{short}_{today}_{n:02d}.mp4'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


# ── 실행 ────────────────────────────────────────────
if __name__ == '__main__':
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        print("=" * 45)
        print("  숏츠 메이커 →  http://localhost:5000")
        print("  종료: Ctrl+C")
        print("=" * 45)
    # threaded=True: SSE 스트리밍과 백그라운드 작업을 위해 필수
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)

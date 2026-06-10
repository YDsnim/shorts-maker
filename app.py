# =====================================================
# app.py — 숏츠 메이커 Flask 메인 앱
# 실행: python app.py  →  http://localhost:5000
# =====================================================

import os
import re
import shutil
import subprocess
import time
import uuid

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

import config
import modules.video_processor as vp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)

_last_cleanup  = 0.0
_whisper_model = None


def safe_filename(name: str) -> bool:
    """경로 조작 공격 방지 — 디렉토리 구분자 포함 여부 확인"""
    return os.sep not in name and '/' not in name and '..' not in name


def sanitize_base(name: str) -> str:
    """파일명 베이스 정리 — OS 금지 문자 제거, 공백→언더스코어"""
    base = name.rsplit('.', 1)[0] if '.' in name else name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', base)
    base = base.strip().replace(' ', '_')
    return base[:80] or 'video'


def make_output_name(base: str) -> str:
    """원본명_crop_N.mp4 형식, 중복 시 N 증가"""
    n = 1
    while True:
        name = f'{base}_crop_{n}.mp4'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def make_srt_name(base: str) -> str:
    """원본명_transcript_N.srt 형식, 중복 시 N 증가"""
    n = 1
    while True:
        name = f'{base}_transcript_{n}.srt'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def cleanup_old_files():
    """OUTPUT_TTL_SECONDS 이상 된 파일을 uploads/·output/ 에서 정리"""
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


def get_whisper_model():
    """Whisper small 모델을 한 번만 로드해 캐시"""
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model('small')
    return _whisper_model


def _sec_to_srt_time(seconds: float) -> str:
    ms = int((seconds % 1) * 1000)
    s  = int(seconds) % 60
    m  = (int(seconds) // 60) % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(segments) -> str:
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _sec_to_srt_time(seg['start'])
        end   = _sec_to_srt_time(seg['end'])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}")
    return '\n\n'.join(lines) + '\n'


def allowed_file(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in config.ALLOWED_EXTENSIONS


# ── 요청마다 오래된 파일 정리 (TTL 주기로만 실행) ────
@app.before_request
def periodic_cleanup():
    cleanup_old_files()


# ── 메인 페이지 ─────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── 업로드된 원본 파일 서빙 (크롭 미리보기용) ─────────
@app.route('/uploads/<filename>')
def serve_upload(filename: str):
    if not safe_filename(filename):
        return '', 404
    path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return '', 404
    return send_file(path)


# ── 영상 업로드 ─────────────────────────────────────
@app.route('/upload', methods=['POST'])
def upload():
    if 'video' not in request.files:
        return jsonify({'ok': False, 'error': '파일이 없습니다.'}), 400

    file = request.files['video']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'ok': False, 'error': f'지원 형식: {", ".join(config.ALLOWED_EXTENSIONS)}'}), 400

    ext           = file.filename.rsplit('.', 1)[-1].lower()
    filename      = f'{uuid.uuid4().hex}.{ext}'
    original_base = sanitize_base(file.filename)
    save_path     = os.path.join(config.UPLOAD_FOLDER, filename)
    file.save(save_path)

    try:
        info = vp.get_video_info(save_path)
    except Exception:
        info = {}

    return jsonify({'ok': True, 'filename': filename, 'original_base': original_base, 'info': info})


# ── 크롭 처리 ───────────────────────────────────────
@app.route('/process', methods=['POST'])
def process():
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')
    crop          = data.get('crop')   # { x, y, w, h } — 실제 픽셀 값

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    input_path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(input_path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    if not crop:
        return jsonify({'ok': False, 'error': '크롭 정보가 없습니다.'}), 400

    result_name = make_output_name(original_base)
    result_path = os.path.join(config.OUTPUT_FOLDER, result_name)

    try:
        vp.crop_custom(
            input_path, result_path,
            x=int(crop['x']), y=int(crop['y']),
            w=int(crop['w']), h=int(crop['h']),
        )
        # 원본 파일을 output/ 으로 이동 (결과물과 같은 공간)
        dst = os.path.join(config.OUTPUT_FOLDER, filename)
        shutil.move(input_path, dst)

        return jsonify({'ok': True, 'result': result_name, 'original': filename})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── YouTube 영상 가져오기 ────────────────────────────
@app.route('/fetch-youtube', methods=['POST'])
def fetch_youtube():
    data = request.get_json(force=True)
    url  = (data.get('url') or '').strip()

    if not url or not re.search(r'(youtube\.com|youtu\.be)', url):
        return jsonify({'ok': False, 'error': '유효하지 않은 YouTube URL'}), 400

    try:
        # 영상 제목 조회
        title_result = subprocess.run(
            ['yt-dlp', '--get-filename', '-o', '%(title)s', '--no-playlist', url],
            capture_output=True, text=True, timeout=30
        )
        raw_title     = title_result.stdout.strip().split('\n')[0] or 'video'
        original_base = sanitize_base(raw_title)

        temp_name = f'{uuid.uuid4().hex}.mp4'
        temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

        subprocess.run(
            [
                'yt-dlp',
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '--no-playlist',
                '-o', temp_path,
                url,
            ],
            capture_output=True, text=True, timeout=300, check=True
        )

        try:
            info = vp.get_video_info(temp_path)
        except Exception:
            info = {}

        return jsonify({'ok': True, 'filename': temp_name, 'original_base': original_base, 'info': info})

    except FileNotFoundError:
        return jsonify({'ok': False, 'error': 'yt-dlp가 설치되지 않았습니다.'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': '다운로드 시간 초과 (5분)'}), 500
    except subprocess.CalledProcessError as e:
        err = (e.stderr or '')[-300:]
        return jsonify({'ok': False, 'error': f'다운로드 실패: {err}'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── 대본 추출 (Whisper STT → SRT) ───────────────────
@app.route('/transcribe', methods=['POST'])
def transcribe():
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    # output/ 우선, 없으면 uploads/ 에서 찾기
    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    try:
        model  = get_whisper_model()
        result = model.transcribe(path, language='ko')

        srt_name = make_srt_name(original_base)
        srt_path = os.path.join(config.OUTPUT_FOLDER, srt_name)
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(_to_srt(result['segments']))

        return jsonify({'ok': True, 'srt': srt_name})

    except ModuleNotFoundError:
        return jsonify({'ok': False, 'error': 'openai-whisper가 설치되지 않았습니다. pip install openai-whisper'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── 결과 다운로드 ────────────────────────────────────
@app.route('/download/<filename>')
def download(filename: str):
    if not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일 없음'}), 404

    return send_file(path, as_attachment=True, download_name=filename)


# ── 실행 ────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 45)
    print("  숏츠 메이커 →  http://localhost:5000")
    print("  종료: Ctrl+C")
    print("=" * 45)
    app.run(debug=True, host='0.0.0.0', port=5000)

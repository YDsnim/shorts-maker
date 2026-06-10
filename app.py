# =====================================================
# app.py — 숏츠 메이커 Flask 메인 앱
# 실행: python app.py  →  http://localhost:5000
# =====================================================

import os
import uuid

from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename

import config
import modules.video_processor as vp

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)


def safe_filename(name: str) -> bool:
    """경로 조작 공격 방지 — 디렉토리 구분자 포함 여부 확인"""
    return os.sep not in name and '/' not in name and '..' not in name


def allowed_file(filename: str) -> bool:
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in config.ALLOWED_EXTENSIONS


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

    ext      = file.filename.rsplit('.', 1)[-1].lower()
    filename = f'{uuid.uuid4().hex}.{ext}'
    save_path = os.path.join(config.UPLOAD_FOLDER, filename)
    file.save(save_path)

    try:
        info = vp.get_video_info(save_path)
    except Exception:
        info = {}

    return jsonify({'ok': True, 'filename': filename, 'info': info})


# ── 크롭 처리 ───────────────────────────────────────
@app.route('/process', methods=['POST'])
def process():
    data     = request.get_json(force=True)
    filename = data.get('filename', '')
    crop     = data.get('crop')   # { x, y, w, h } — 실제 픽셀 값

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    input_path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(input_path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    if not crop:
        return jsonify({'ok': False, 'error': '크롭 정보가 없습니다.'}), 400

    result_name = f'shorts_{uuid.uuid4().hex[:8]}.mp4'
    result_path = os.path.join(config.OUTPUT_FOLDER, result_name)

    try:
        vp.crop_custom(
            input_path, result_path,
            x=int(crop['x']), y=int(crop['y']),
            w=int(crop['w']), h=int(crop['h']),
        )
        return jsonify({'ok': True, 'result': result_name})

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

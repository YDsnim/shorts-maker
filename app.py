# =====================================================
# app.py — 숏츠 메이커 Flask 메인 앱
#
# 역할:
#   · 브라우저와 서버 사이의 모든 HTTP 통신을 담당
#   · 파일 업로드, 크롭, YouTube 다운로드, STT, 다운로드 등
#     각 기능별 엔드포인트(API 주소)를 정의한다
#   · 영상 실제 처리는 modules/video_processor.py 에 위임
#
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
# Flask가 허용하는 최대 업로드 크기를 config에서 읽어 설정
# 이 값을 초과하는 요청은 Flask가 자동으로 413 에러로 거부한다
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# 앱 시작 시 저장 폴더가 없으면 미리 만들어둔다
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)

# ── 전역 상태 변수 ────────────────────────────────────
# 마지막으로 cleanup을 실행한 시각 (Unix timestamp, 초 단위)
# 모든 요청에서 공유되어야 하므로 전역으로 선언한다
_last_cleanup  = 0.0

# Whisper 모델 캐시: 처음 요청 시 로드한 뒤 재사용
# 모델 로딩이 수 초~수십 초 걸리기 때문에 요청마다 다시 로드하지 않는다
_whisper_model = None


# ─────────────────────────────────────────────────────
# 헬퍼 함수 모음
# ─────────────────────────────────────────────────────

def safe_filename(name: str) -> bool:
    """
    파일명에 경로 조작 문자가 있는지 검사한다.

    공격자가 '../../../etc/passwd' 같은 경로를 파일명으로 보내
    서버의 임의 파일에 접근하는 '경로 순회 공격'을 막기 위해
    디렉토리 구분자( / \ ..)가 포함되어 있으면 False를 반환한다.
    """
    return os.sep not in name and '/' not in name and '..' not in name


def sanitize_base(name: str) -> str:
    """
    사용자 파일명에서 다운로드용 베이스 문자열을 만든다.

    1단계: 확장자 제거   'my video.mp4'  →  'my video'
    2단계: OS 금지 문자 제거  < > : " / \\ | ? * 및 제어문자
           (Windows·Linux 양쪽에서 파일명으로 쓸 수 없는 문자들)
    3단계: 앞뒤 공백 제거 후 공백 → 언더스코어
    4단계: 80자 초과 시 잘라냄 (파일시스템 경로 길이 제한 대비)
    5단계: 결과가 빈 문자열이면 기본값 'video' 반환
    """
    base = name.rsplit('.', 1)[0] if '.' in name else name
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', base)
    base = base.strip().replace(' ', '_')
    return base[:80] or 'video'


def make_output_name(base: str) -> str:
    """
    크롭 결과 파일명을 생성한다: {원본명}_crop_{N}.mp4

    같은 이름의 파일이 이미 output/ 에 있으면 N을 1씩 올린다.
    예) 여름휴가_crop_1.mp4 가 있으면 → 여름휴가_crop_2.mp4
    """
    n = 1
    while True:
        name = f'{base}_crop_{n}.mp4'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def make_srt_name(base: str) -> str:
    """
    SRT 대본 파일명을 생성한다: {원본명}_transcript_{N}.srt

    make_output_name과 같은 중복 방지 로직을 사용한다.
    """
    n = 1
    while True:
        name = f'{base}_transcript_{n}.srt'
        if not os.path.exists(os.path.join(config.OUTPUT_FOLDER, name)):
            return name
        n += 1


def cleanup_old_files():
    """
    오래된 임시 파일을 정리한다 (TTL 기반 자동 삭제).

    동작 원리:
      · 마지막 실행으로부터 OUTPUT_TTL_SECONDS(기본 1시간)가 지나지 않았으면
        아무것도 하지 않고 즉시 반환한다 → 매 요청마다 불필요한 디스크 탐색 방지
      · 충분한 시간이 지났을 때만 uploads/ 와 output/ 을 순회하며
        수정 시각이 TTL을 초과한 파일을 삭제한다
      · os.remove 실패(파일이 이미 없거나 권한 문제)는 무시한다 — 정리 실패가
        사용자 요청에 영향을 주면 안 되기 때문이다
    """
    global _last_cleanup
    now = time.time()
    # 아직 정리 주기가 안 됐으면 바로 종료
    if now - _last_cleanup < config.OUTPUT_TTL_SECONDS:
        return
    _last_cleanup = now
    cutoff = now - config.OUTPUT_TTL_SECONDS  # 이 시각보다 오래된 파일 삭제
    for folder in (config.OUTPUT_FOLDER, config.UPLOAD_FOLDER):
        for fname in os.listdir(folder):
            fpath = os.path.join(folder, fname)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
            except OSError:
                pass  # 삭제 실패는 조용히 무시


def get_whisper_model():
    """
    Whisper 모델을 반환한다 (처음 한 번만 로드, 이후 캐시 재사용).

    Whisper small 모델은 첫 실행 시 약 483MB를 다운로드하고
    메모리에 로드하는 데 수 초가 걸린다.
    전역 변수 _whisper_model 에 저장해두면 두 번째 요청부터는
    이미 메모리에 올라와 있는 모델을 바로 사용할 수 있다.
    """
    global _whisper_model
    if _whisper_model is None:
        import whisper  # 설치 안 됐을 때 에러를 호출 시점에 발생시키기 위해 여기서 임포트
        _whisper_model = whisper.load_model('small')
    return _whisper_model


def _sec_to_srt_time(seconds: float) -> str:
    """
    초 단위 시간을 SRT 타임스탬프 형식으로 변환한다.

    SRT 형식: HH:MM:SS,mmm  (시:분:초,밀리초)
    예) 75.5초  →  '00:01:15,500'
    """
    ms = int((seconds % 1) * 1000)   # 소수 부분 → 밀리초
    s  = int(seconds) % 60
    m  = (int(seconds) // 60) % 60
    h  = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _to_srt(segments) -> str:
    """
    Whisper가 반환한 세그먼트 목록을 SRT 파일 문자열로 변환한다.

    SRT 형식:
        1
        00:00:00,000 --> 00:00:03,420
        안녕하세요.

        2
        00:00:03,420 --> 00:00:06,800
        오늘은 숏츠를 만들어 볼게요.

    각 세그먼트 사이는 빈 줄로 구분되고, 파일 끝에 개행을 붙인다.
    """
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _sec_to_srt_time(seg['start'])
        end   = _sec_to_srt_time(seg['end'])
        lines.append(f"{i}\n{start} --> {end}\n{seg['text'].strip()}")
    return '\n\n'.join(lines) + '\n'


def allowed_file(filename: str) -> bool:
    """파일 확장자가 허용 목록(config.ALLOWED_EXTENSIONS)에 있는지 확인한다."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in config.ALLOWED_EXTENSIONS


# ─────────────────────────────────────────────────────
# 훅: 모든 요청 전에 실행
# ─────────────────────────────────────────────────────

@app.before_request
def periodic_cleanup():
    """
    매 HTTP 요청 직전에 호출된다.
    cleanup_old_files() 내부에서 주기 체크를 하므로
    실제 파일 삭제는 1시간에 한 번만 일어난다.
    별도 스케줄러(APScheduler 등)를 추가하지 않아도 되는 이유다.
    """
    cleanup_old_files()


# ─────────────────────────────────────────────────────
# 라우트 (HTTP 엔드포인트)
# ─────────────────────────────────────────────────────

@app.route('/')
def index():
    """메인 페이지: templates/index.html 을 렌더링해서 반환한다."""
    return render_template('index.html')


@app.route('/uploads/<filename>')
def serve_upload(filename: str):
    """
    업로드된 원본 영상을 브라우저로 스트리밍한다.

    크롭 UI에서 <video> 태그가 원본 영상을 미리보기할 때 사용한다.
    safe_filename 검사로 경로 조작 공격을 차단한다.
    """
    if not safe_filename(filename):
        return '', 404
    path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return '', 404
    return send_file(path)


@app.route('/upload', methods=['POST'])
def upload():
    """
    브라우저에서 선택한 영상 파일을 서버 uploads/ 에 저장한다.

    파일명을 UUID로 바꾸는 이유:
      · 사용자마다 '영상.mp4' 같은 중복 이름을 올릴 수 있으므로
        서버 내부에서는 UUID를 식별자로 사용해 충돌을 방지한다
      · 원본 파일명(원본 베이스)은 따로 추출해서 응답에 포함시키고
        다운로드 파일명 생성에 활용한다

    응답 JSON:
      ok           : 성공 여부
      filename     : 서버에 저장된 UUID 기반 파일명 (내부 식별용)
      original_base: 정리된 원본 파일명 베이스 (다운로드명 생성용)
      info         : 영상 해상도·길이 등 메타데이터
    """
    if 'video' not in request.files:
        return jsonify({'ok': False, 'error': '파일이 없습니다.'}), 400

    file = request.files['video']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'ok': False, 'error': f'지원 형식: {", ".join(config.ALLOWED_EXTENSIONS)}'}), 400

    ext           = file.filename.rsplit('.', 1)[-1].lower()
    filename      = f'{uuid.uuid4().hex}.{ext}'   # UUID 파일명 생성
    original_base = sanitize_base(file.filename)  # 다운로드명 베이스 추출
    save_path     = os.path.join(config.UPLOAD_FOLDER, filename)
    file.save(save_path)

    try:
        info = vp.get_video_info(save_path)  # ffprobe로 영상 메타데이터 읽기
    except Exception:
        info = {}  # 메타데이터 조회 실패해도 업로드 자체는 성공으로 처리

    return jsonify({'ok': True, 'filename': filename, 'original_base': original_base, 'info': info})


@app.route('/process', methods=['POST'])
def process():
    """
    크롭 처리를 수행한다.

    브라우저에서 사용자가 드래그로 지정한 크롭 영역 좌표를 받아
    ffmpeg crop 필터로 영상을 잘라낸 뒤 output/ 에 저장한다.

    크롭 완료 후 원본 파일도 uploads/ → output/ 으로 이동한다.
    이유: 대본 추출 등 후속 작업에서 원본이 필요할 수 있고,
          output/ 의 TTL 정리가 결과물과 원본을 함께 처리해 깔끔하다.

    요청 JSON:
      filename     : 서버 내부 UUID 파일명
      original_base: 다운로드 파일명 베이스
      crop         : { x, y, w, h } — 실제 영상 픽셀 좌표

    응답 JSON:
      result  : 크롭된 결과 파일명 (output/ 기준)
      original: output/ 으로 이동된 원본 파일명
    """
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

    result_name = make_output_name(original_base)  # 충돌 없는 결과 파일명 생성
    result_path = os.path.join(config.OUTPUT_FOLDER, result_name)

    try:
        vp.crop_custom(
            input_path, result_path,
            x=int(crop['x']), y=int(crop['y']),
            w=int(crop['w']), h=int(crop['h']),
        )

        # 크롭 성공 후 원본을 output/ 으로 이동
        # (uploads/ 에는 더 이상 남겨둘 필요가 없고
        #  output/ TTL 정리가 원본·결과물을 함께 처리한다)
        dst = os.path.join(config.OUTPUT_FOLDER, filename)
        shutil.move(input_path, dst)

        return jsonify({'ok': True, 'result': result_name, 'original': filename})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/fetch-youtube', methods=['POST'])
def fetch_youtube():
    """
    YouTube URL에서 영상을 다운로드해 uploads/ 에 저장한다.

    동작 순서:
      1. yt-dlp --get-filename 으로 영상 제목만 먼저 가져온다
      2. UUID 파일명으로 최고 화질 mp4를 다운로드한다
         (mp4+m4a 조합 → ffmpeg 자동 병합)
      3. 파일 저장 후 영상 메타데이터를 읽어 응답에 포함한다

    타임아웃 설정:
      · 제목 조회: 30초 (네트워크 응답 확인용)
      · 실제 다운로드: 300초 (5분, 긴 영상 대비)

    오류 처리:
      · FileNotFoundError  — yt-dlp가 서버에 설치되지 않은 경우
      · TimeoutExpired     — 다운로드가 5분 안에 완료되지 않은 경우
      · CalledProcessError — yt-dlp가 오류 종료한 경우 (비공개 영상 등)
    """
    data = request.get_json(force=True)
    url  = (data.get('url') or '').strip()

    # youtube.com 또는 youtu.be 도메인인지 간단히 검증
    if not url or not re.search(r'(youtube\.com|youtu\.be)', url):
        return jsonify({'ok': False, 'error': '유효하지 않은 YouTube URL'}), 400

    try:
        # 1단계: 영상 제목 조회 (다운로드 없이 제목만)
        title_result = subprocess.run(
            ['yt-dlp', '--get-filename', '-o', '%(title)s', '--no-playlist', url],
            capture_output=True, text=True, timeout=30
        )
        raw_title     = title_result.stdout.strip().split('\n')[0] or 'video'
        original_base = sanitize_base(raw_title)

        # 2단계: UUID 파일명으로 실제 다운로드
        temp_name = f'{uuid.uuid4().hex}.mp4'
        temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

        subprocess.run(
            [
                'yt-dlp',
                # 최고화질 mp4 비디오 + m4a 오디오를 선택해 ffmpeg로 합친다
                # 해당 조합이 없으면 단순 mp4 최고화질, 그것도 없으면 최고화질 폴백
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                '--no-playlist',   # 재생목록 전체가 아닌 단일 영상만 다운로드
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
        # stderr 마지막 300자만 잘라서 응답 (비공개 영상·저작권 차단 등 원인 표시)
        err = (e.stderr or '')[-300:]
        return jsonify({'ok': False, 'error': f'다운로드 실패: {err}'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/transcribe', methods=['POST'])
def transcribe():
    """
    영상에서 음성을 인식해 SRT 대본 파일을 생성한다.

    동작 순서:
      1. 파일을 output/ 에서 먼저 찾고, 없으면 uploads/ 에서 찾는다
         (크롭 완료 후에는 원본이 output/ 으로 이동되어 있기 때문)
      2. Whisper small 모델로 음성 인식 (language='ko' 로 한국어 고정)
      3. 결과 세그먼트를 SRT 형식으로 변환해 output/ 에 저장
      4. 저장된 SRT 파일명을 응답으로 반환 → 브라우저가 즉시 다운로드

    주의사항:
      · 첫 호출 시 Whisper 모델(483MB)을 다운로드하고 메모리에 로드한다
      · 영상 길이에 따라 수십 초가 소요될 수 있다
      · Flask는 단일 스레드이므로 처리 중 다른 요청은 대기한다

    요청 JSON:
      filename     : 서버 내부 UUID 파일명
      original_base: SRT 파일명 베이스

    응답 JSON:
      srt: 생성된 SRT 파일명 (output/ 기준, /download/ 로 내려받기 가능)
    """
    data          = request.get_json(force=True)
    filename      = data.get('filename', '')
    original_base = sanitize_base(data.get('original_base', '') or 'video')

    if not filename or not safe_filename(filename):
        return jsonify({'ok': False, 'error': '잘못된 파일명'}), 400

    # 크롭 완료 후에는 output/, 크롭 전이라면 uploads/ 에 파일이 있다
    path = os.path.join(config.OUTPUT_FOLDER, filename)
    if not os.path.exists(path):
        path = os.path.join(config.UPLOAD_FOLDER, filename)
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': '파일을 찾을 수 없습니다.'}), 404

    try:
        model  = get_whisper_model()                    # 캐시된 모델 반환
        result = model.transcribe(path, language='ko')  # 한국어로 음성 인식

        srt_name = make_srt_name(original_base)         # 충돌 없는 SRT 파일명
        srt_path = os.path.join(config.OUTPUT_FOLDER, srt_name)
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write(_to_srt(result['segments']))        # 세그먼트 → SRT 변환 후 저장

        return jsonify({'ok': True, 'srt': srt_name})

    except ModuleNotFoundError:
        # openai-whisper 패키지가 없을 때 사용자에게 설치 방법 안내
        return jsonify({'ok': False, 'error': 'openai-whisper가 설치되지 않았습니다. pip install openai-whisper'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/download/<filename>')
def download(filename: str):
    """
    output/ 폴더의 파일을 브라우저로 다운로드한다.

    as_attachment=True  : 브라우저가 페이지를 열지 않고 파일로 저장하도록 지시
    download_name       : 다운로드 시 표시될 파일명
                          (서버 내부 파일명과 동일하게 유지)
    .mp4, .srt 등 확장자에 관계없이 모두 처리한다.
    """
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

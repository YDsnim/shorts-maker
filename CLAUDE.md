# shorts-maker 프로젝트 인수인계

## 사용자 환경
- GPU: GTX 1070 Ti AORUS (VRAM 8GB, Pascal / CUDA 지원)
- OS: Windows
- 앱 실행: `run.bat` 더블클릭 (포트 5000)

## 프로젝트 개요
유튜브 숏츠 제작 웹앱. Flask 기반, 두 가지 파이프라인 존재:
- `/process` — 원본 영상 크롭 + 배경 처리 (수동 드래그)
- `/pipeline/run` — 내레이션 영상 자동 제작 (TTS + Whisper + ffmpeg)

## 현재 구성 (최신 상태 기준)

### 텍스트 구조 (3단계)
1. **제목** — 상단 배너 또는 타이틀 오버레이
2. **자막** — Whisper가 TTS 음성 분석해서 자동 생성
3. **추가텍스트** (선택) — 가로줄(바) 스타일로 렌더링 (`_draw_layer_bar`)

source_text, text_overlays 시스템은 완전 제거됨 (PR#6에서 정리)

### 템플릿
- `namnam` — 단색 어두운 배경 + 상단 배너 바
- `silver_crown` — PNG 배경 + 제목 텍스트 오버레이

### Whisper 설정
- 모델: `large-v3-turbo` (float16, CUDA)
- 한국어 특화 설정:
  ```python
  vad_filter=True
  vad_parameters={'min_silence_duration_ms': 300}
  condition_on_previous_text=False
  no_speech_threshold=0.6
  initial_prompt='안녕하세요.'
  ```
- medium 모델은 `run.bat` 실행 시 자동 삭제됨

## 브랜치 전략
- 작업 브랜치: `claude/video-filename-recommendation-kzg438`
- PR: main으로 머지 (PR#6 오픈 상태)
- 새 작업도 이 브랜치 또는 새 `claude/*` 브랜치에서 진행

## 주요 파일
| 파일 | 역할 |
|------|------|
| `app.py` | Flask 서버, 모든 API 엔드포인트 |
| `auto_pipeline/assemble.py` | 내레이션 영상 조립 파이프라인 |
| `modules/banner.py` | 배너/오버레이 PNG 생성 (Pillow) |
| `modules/subtitle.py` | ASS 자막 파일 생성 |
| `modules/template.py` | 템플릿 상수 및 설정값 |
| `templates/index.html` | 프론트엔드 UI |
| `static/js/main.js` | 프론트엔드 JS 로직 |
| `run.bat` | Windows 앱 시작 스크립트 |

## 알려진 이슈 / 논의 중인 기능
- 자막 타이밍 품질: large-v3-turbo로 개선 중 (이전 medium 대비 향상 예정)
- 원본 영상 소스 추출 (남의 숏츠 배경만 따기): 미구현, cropdetect 방식 검토 중
- 무음 구간 자동 컷편집: 미구현, ffmpeg silencedetect 방식 검토 중

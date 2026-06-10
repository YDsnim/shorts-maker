/* =====================================================
   main.js — 숏츠 메이커 (비주얼 크롭 UI)

   역할:
     · 파일 업로드 / YouTube URL 가져오기
     · 크롭 박스 드래그 UI (마우스·터치 모두 지원)
     · 서버 API 호출 및 결과 처리 (크롭, 대본 추출, 다운로드)

   서버와의 통신은 모두 fetch() 비동기 호출로 이루어진다.
   ===================================================== */

// ── 전역 상태 ────────────────────────────────────────
// 서버에 저장된 UUID 기반 파일명 (예: a3f9c1d2.mp4)
// 크롭·대본 요청 시 서버가 어느 파일을 처리할지 식별하는 데 쓴다
let uploadedFilename = null;

// 다운로드 파일명에 쓸 원본 베이스 (예: '여름휴가')
// 서버가 결과 파일명을 만들 때 사용한다: 여름휴가_crop_1.mp4
let originalBase     = null;

// 실제 영상 픽셀 크기 — 크롭 좌표 계산의 기준이 된다
let videoDim = { w: 0, h: 0 };

// 현재 크롭 영역 (실제 픽셀 단위, 화면 표시 좌표가 아님)
// 서버로 그대로 전송해 ffmpeg에 넘긴다
let cropPx   = { x: 0, y: 0, w: 0, h: 0 };

// 크롭 박스의 최소 크기 — 이 값보다 작게 드래그하면 보정된다
const MIN_PX = 20;

// ── DOM 참조 ─────────────────────────────────────────
// 자주 쓰는 HTML 요소들을 변수에 담아 getElementById 반복 호출을 줄인다
const ytUrl          = document.getElementById('yt-url');
const ytBtn          = document.getElementById('yt-btn');
const dropZone       = document.getElementById('drop-zone');
const transcribeBtn  = document.getElementById('transcribe-btn');
const transcribeSec  = document.getElementById('transcribe-section');
const fileInput    = document.getElementById('file-input');
const cropCard     = document.getElementById('crop-card');
const actionCard   = document.getElementById('action-card');
const cropContainer = document.getElementById('crop-container');
const previewVideo = document.getElementById('preview-video');
const cropBox      = document.getElementById('crop-box');
const lock916      = document.getElementById('lock-916');
const resetBtn     = document.getElementById('reset-btn');
const processBtn   = document.getElementById('process-btn');
const progressSec  = document.getElementById('progress-section');
const resultSec    = document.getElementById('result-section');
const cropDims     = document.getElementById('crop-dims');
const ratioBadge   = document.getElementById('ratio-badge');
const toast        = document.getElementById('toast');

/* ====================================================
   업로드 — 드래그&드롭 / 클릭 파일 선택
   ==================================================== */

// 드롭 존 클릭 → 숨겨진 file input 트리거
dropZone.addEventListener('click', () => fileInput.click());

// 파일을 드래그해서 올려놓는 도중 기본 브라우저 동작(파일 열기)을 막는다
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));

// 파일을 드롭했을 때
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});

// 파일 선택 다이얼로그에서 파일 선택 완료 시
fileInput.addEventListener('change', () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
  // 브라우저에서 먼저 파일 크기를 체크해 불필요한 전송을 차단
  if (file.size > 500 * 1024 * 1024) { showToast('파일이 500MB를 초과합니다.', 'error'); return; }

  dropZone.innerHTML = `<strong>업로드 중...</strong><p>${file.name}</p>`;

  // FormData를 사용해 멀티파트로 파일 전송 (Content-Type은 자동 설정됨)
  const form = new FormData();
  form.append('video', file);

  try {
    const res  = await fetch('/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!data.ok) { showToast(data.error || '업로드 실패', 'error'); resetDrop(); return; }

    // 서버가 반환한 UUID 파일명과 원본 베이스를 전역에 저장
    uploadedFilename = data.filename;
    originalBase     = data.original_base || 'video';

    dropZone.innerHTML = `
      <strong>✅ ${file.name}</strong>
      <p style="color:var(--success)">업로드 완료 · 다시 클릭하면 교체</p>
    `;

    // 서버가 ffprobe로 읽어온 해상도·길이를 표시
    const info = data.info || {};
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    initCropUI(data.filename, info);
    showToast('업로드 완료!', 'success');

  } catch { showToast('네트워크 오류', 'error'); resetDrop(); }
}

/* ====================================================
   크롭 UI 초기화
   ==================================================== */
function initCropUI(filename, info) {
  // 실제 영상 크기를 전역에 저장 — 크롭 좌표 계산의 기준이 된다
  // 서버에서 정보를 못 받았을 때를 대비해 기본값(1280×720)을 설정
  videoDim = { w: info.width || 1280, h: info.height || 720 };

  // <video> 태그에 원본 파일 경로를 연결한다
  // 브라우저가 이 URL로 영상을 스트리밍하면서 크롭 미리보기에 사용
  previewVideo.src = `/uploads/${filename}`;
  previewVideo.currentTime = 0;

  // { once: true } : 메타데이터 로드 이벤트는 한 번만 처리한다
  // 같은 파일을 다시 올릴 때 이벤트가 중복으로 쌓이는 문제를 방지
  previewVideo.addEventListener('loadedmetadata', () => {
    initCropBox();
    cropCard.style.display  = 'block';
    actionCard.style.display = 'block';

    // 이미 9:16 비율인 영상은 '이미 9:16입니다' 배지를 보여준다
    const ratio = videoDim.w / videoDim.h;
    const is916 = Math.abs(ratio - 9 / 16) < 0.01;
    ratioBadge.style.display = is916 ? 'block' : 'none';
  }, { once: true });
}

function initCropBox() {
  const vw = videoDim.w, vh = videoDim.h;
  const ratio = vw / vh;
  const target = 9 / 16;  // 숏츠 표준 비율

  if (ratio > target + 0.01) {
    // 가로가 더 넓은 영상(예: 16:9 유튜브 영상):
    // 높이는 원본 그대로, 폭만 9:16 비율로 계산해 가운데 배치
    const cw = Math.round(vh * target);
    const cx = Math.round((vw - cw) / 2);
    cropPx = { x: cx, y: 0, w: cw, h: vh };
    lock916.checked = true;  // 9:16 비율 잠금 자동 활성화
  } else {
    // 이미 세로이거나 9:16에 가까운 영상 → 전체를 선택 상태로 시작
    cropPx = { x: 0, y: 0, w: vw, h: vh };
  }

  renderCropBox();
}

/* ====================================================
   크롭 박스 렌더 (픽셀 → 화면 좌표 변환)

   핵심 개념:
     · cropPx 는 실제 영상 픽셀 단위의 좌표 (서버로 보내는 값)
     · CSS 좌표는 화면에 표시되는 영상 크기 기준이므로
       scaleX/scaleY 비율로 변환해야 크롭 박스가 맞는 위치에 그려진다
   ==================================================== */
function renderCropBox() {
  const displayW = cropContainer.offsetWidth;
  // 컨테이너 높이는 영상 원본 비율에 맞게 계산 (CSS로 고정하지 않음)
  const displayH = displayW / videoDim.w * videoDim.h;

  const scaleX = displayW / videoDim.w;  // 화면 픽셀 / 영상 픽셀
  const scaleY = displayH / videoDim.h;

  // 크롭 박스의 CSS 위치·크기를 화면 좌표로 변환해 적용
  cropBox.style.left   = (cropPx.x * scaleX) + 'px';
  cropBox.style.top    = (cropPx.y * scaleY) + 'px';
  cropBox.style.width  = (cropPx.w * scaleX) + 'px';
  cropBox.style.height = (cropPx.h * scaleY) + 'px';

  // 화면 하단에 현재 크롭 크기와 비율을 텍스트로 표시
  const w = Math.round(cropPx.w);
  const h = Math.round(cropPx.h);
  const r = (w / h).toFixed(2);
  cropDims.textContent = `결과: ${w} × ${h} px  (${r} : 1)`;
}

// 창 크기가 바뀌면 화면 픽셀 비율이 달라지므로 크롭 박스를 다시 그린다
window.addEventListener('resize', () => { if (uploadedFilename) renderCropBox(); });

/* ====================================================
   드래그 핸들 이벤트

   크롭 박스 테두리의 8개 핸들(n·s·e·w·ne·nw·se·sw)과
   박스 중앙을 드래그해 위치·크기를 조절한다.
   마우스와 터치(모바일) 이벤트를 모두 처리한다.
   ==================================================== */
let drag = null; // 드래그 중 상태: { dir, startCX, startCY, startCrop }

// 핸들 각각에 드래그 시작 이벤트 등록
cropBox.querySelectorAll('.handle').forEach(handle => {
  handle.addEventListener('mousedown',  e => startDrag(e, handle.dataset.dir));
  handle.addEventListener('touchstart', e => startDrag(e, handle.dataset.dir), { passive: false });
});

// 크롭 박스 자체(핸들이 아닌 빈 영역)를 드래그하면 이동 모드
cropBox.addEventListener('mousedown',  e => { if (e.target === cropBox) startDrag(e, 'move'); });
cropBox.addEventListener('touchstart', e => { if (e.target === cropBox) startDrag(e, 'move'); }, { passive: false });

function startDrag(e, dir) {
  e.preventDefault();   // 텍스트 선택, 페이지 스크롤 등 기본 동작 차단
  e.stopPropagation();  // 부모 요소로 이벤트가 전파되지 않도록 막는다
  const pt = getPoint(e);
  // 드래그 시작 시점의 마우스 좌표와 크롭 상태를 저장해두고
  // onDragMove에서 이동량(delta)을 계산하는 기준으로 사용한다
  drag = { dir, startCX: pt.x, startCY: pt.y, startCrop: { ...cropPx } };
}

// mousemove·touchmove는 document 전체에서 받는다
// cropBox 밖으로 빠르게 드래그해도 이동이 끊기지 않도록 하기 위함
document.addEventListener('mousemove',  onDragMove);
document.addEventListener('touchmove',  onDragMove, { passive: false });
document.addEventListener('mouseup',    () => { drag = null; });
document.addEventListener('touchend',   () => { drag = null; });

function onDragMove(e) {
  if (!drag) return;
  e.preventDefault();

  const pt = getPoint(e);
  // 마우스 이동량을 화면 크기 대비 비율로 환산해 실제 픽셀 이동량으로 변환
  // displayW·displayH: 화면에 보이는 영상 크기
  // dvx·dvy: 실제 영상 픽셀 단위의 이동량
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;
  const dvx = (pt.x - drag.startCX) / displayW  * videoDim.w;
  const dvy = (pt.y - drag.startCY) / displayH * videoDim.h;

  // 드래그 시작 시점의 크롭 상태를 기준으로 새 위치를 계산한다
  // (현재 cropPx가 아닌 startCrop을 기준으로 해야 드래그가 부드럽다)
  const sc   = drag.startCrop;
  const lock = lock916.checked;  // 9:16 비율 잠금 여부
  let { x, y, w, h } = sc;

  switch (drag.dir) {
    // ── 이동: 크기는 유지하고 위치만 변경 ─────────────
    case 'move':
      x = clamp(sc.x + dvx, 0, videoDim.w - sc.w);
      y = clamp(sc.y + dvy, 0, videoDim.h - sc.h);
      break;

    // ── 위쪽 핸들: 위로 드래그하면 크롭 박스가 위로 커짐 ──
    case 'n': {
      const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      h = sc.h - (ny - sc.y);
      y = ny;
      // 9:16 잠금 시: 높이에 맞춰 폭 자동 조정, 수평 중앙 유지
      if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    // ── 아래쪽 핸들 ──────────────────────────────────
    case 's': {
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    // ── 오른쪽 핸들 ──────────────────────────────────
    case 'e': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      if (lock) { h = w * (16/9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    // ── 왼쪽 핸들 ────────────────────────────────────
    case 'w': {
      const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      w = sc.w - (nx - sc.x);
      x = nx;
      if (lock) { h = w * (16/9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    // ── 모서리 핸들들 (대각선 방향으로 크기 조절) ───────
    case 'nw': {
      const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      w = sc.w - (nx - sc.x);  h = sc.h - (ny - sc.y);
      x = nx; y = ny;
      if (lock) { h = w * (16/9); y = sc.y + sc.h - h; }
      break;
    }
    case 'ne': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      const ny2 = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      h = sc.h - (ny2 - sc.y); y = ny2;
      if (lock) { h = w * (16/9); y = sc.y + sc.h - h; }
      break;
    }
    case 'sw': {
      const nx2 = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      w = sc.w - (nx2 - sc.x); x = nx2;
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { h = w * (16/9); }
      break;
    }
    case 'se': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { h = w * (16/9); }
      break;
    }
  }

  // 영상 범위를 절대로 벗어나지 않도록 최종 보정
  w = clamp(w, MIN_PX, videoDim.w);
  h = clamp(h, MIN_PX, videoDim.h);
  x = clamp(x, 0, videoDim.w - w);
  y = clamp(y, 0, videoDim.h - h);

  cropPx = { x, y, w, h };
  renderCropBox();
}

/* ====================================================
   초기화 버튼 — 크롭 박스를 처음 상태로 되돌린다
   ==================================================== */
resetBtn.addEventListener('click', initCropBox);

/* ====================================================
   처리 (크롭 적용)

   서버 /process 에 현재 크롭 좌표를 전송하면
   ffmpeg가 영상을 잘라내고 결과 파일명을 반환한다.
   ==================================================== */
processBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  processBtn.disabled       = true;
  resultSec.style.display   = 'none';
  progressSec.style.display = 'block';

  try {
    const res  = await fetch('/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename:      uploadedFilename,   // 서버 내부 UUID 파일명
        original_base: originalBase,       // 결과 파일명에 쓸 원본 베이스
        crop: {
          // Math.round: 소수점 픽셀을 정수로 변환 (ffmpeg 정수 요구)
          x: Math.round(cropPx.x),
          y: Math.round(cropPx.y),
          w: Math.round(cropPx.w),
          h: Math.round(cropPx.h),
        },
      }),
    });
    const data = await res.json();

    progressSec.style.display = 'none';

    if (!data.ok) { showToast(data.error || '처리 실패', 'error'); processBtn.disabled = false; return; }

    // 크롭 완료 후 원본은 output/ 으로 이동됐으므로
    // 이후 대본 추출 요청 시 서버가 output/ 에서 파일을 찾을 수 있도록 갱신
    if (data.original) uploadedFilename = data.original;

    const dlBtn = document.getElementById('download-btn');
    dlBtn.href     = `/download/${data.result}`;
    dlBtn.download = data.result;
    resultSec.style.display = 'block';
    showToast('완성!', 'success');

  } catch {
    progressSec.style.display = 'none';
    processBtn.disabled = false;
    showToast('오류가 발생했습니다.', 'error');
  }
});

/* ====================================================
   대본 추출 (Whisper STT → SRT)

   서버 /transcribe 에 파일명을 전송하면
   Whisper AI가 음성을 인식해 SRT 파일을 생성한다.
   생성된 SRT를 즉시 다운로드한다.
   ==================================================== */
transcribeBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  transcribeBtn.disabled      = true;
  transcribeSec.style.display = 'block';  // 진행 중 표시

  try {
    const res  = await fetch('/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: uploadedFilename, original_base: originalBase }),
    });
    const data = await res.json();

    transcribeSec.style.display = 'none';

    if (!data.ok) { showToast(data.error || '대본 추출 실패', 'error'); return; }

    // <a> 태그를 동적으로 만들어 클릭하면 파일 다운로드가 시작된다
    // download 속성이 있으면 브라우저가 파일로 저장한다
    const a = document.createElement('a');
    a.href     = `/download/${data.srt}`;
    a.download = data.srt;
    a.click();
    showToast('대본 추출 완료!', 'success');

  } catch {
    transcribeSec.style.display = 'none';
    showToast('오류가 발생했습니다.', 'error');
  } finally {
    // 성공·실패 모두 버튼을 다시 활성화한다 (finally는 항상 실행됨)
    transcribeBtn.disabled = false;
  }
});

/* ====================================================
   YouTube 가져오기

   YouTube URL을 서버에 전달하면 yt-dlp가 다운로드하고
   완료 후 일반 업로드와 동일한 크롭 워크플로로 진입한다.
   ==================================================== */
ytBtn.addEventListener('click', fetchYoutube);
// Enter 키로도 가져오기 가능하도록 처리
ytUrl.addEventListener('keydown', e => { if (e.key === 'Enter') fetchYoutube(); });

async function fetchYoutube() {
  const url = ytUrl.value.trim();
  if (!url) return;

  ytBtn.disabled    = true;
  ytBtn.textContent = '⏳ 다운로드 중...';
  dropZone.innerHTML = `<strong>YouTube 영상 다운로드 중...</strong><p>${url}</p>`;

  try {
    const res  = await fetch('/fetch-youtube', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!data.ok) {
      showToast(data.error || '다운로드 실패', 'error');
      resetDrop();
      return;
    }

    // 업로드와 동일하게 전역 상태 설정
    uploadedFilename = data.filename;
    originalBase     = data.original_base || 'video';

    dropZone.innerHTML = `
      <strong>✅ ${data.original_base}</strong>
      <p style="color:var(--success)">YouTube 다운로드 완료 · 다시 클릭하면 교체</p>
    `;

    const info = data.info || {};
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    // 크롭 UI 초기화 (일반 업로드와 동일한 흐름으로 진입)
    initCropUI(data.filename, info);
    showToast('YouTube 영상 준비 완료!', 'success');
    ytUrl.value = '';

  } catch {
    showToast('네트워크 오류', 'error');
    resetDrop();
  } finally {
    ytBtn.disabled    = false;
    ytBtn.textContent = '▶ 가져오기';
  }
}

/* ====================================================
   유틸리티 함수
   ==================================================== */

// 값을 min~max 범위 안으로 제한한다 (크롭 박스가 영상 밖으로 나가지 않도록)
function clamp(v, min, max) { return Math.min(Math.max(v, min), max); }

// 마우스와 터치 이벤트에서 통일된 좌표를 반환한다
function getPoint(e) {
  if (e.touches && e.touches.length) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
  return { x: e.clientX, y: e.clientY };
}

// 드롭 존을 초기 상태 텍스트로 되돌린다 (업로드 실패 등)
function resetDrop() {
  dropZone.innerHTML = `<strong>영상을 여기에 끌어다 놓거나 클릭하세요</strong><p>MP4, MOV, AVI, MKV, WebM · 최대 500MB</p>`;
}

// 화면 하단에 토스트 메시지를 3초간 표시한다
let toastTimer;
function showToast(msg, type = '') {
  clearTimeout(toastTimer);  // 이전 토스트가 남아있으면 타이머 취소
  toast.textContent  = msg;
  toast.className    = 'show ' + type;
  toastTimer = setTimeout(() => { toast.className = ''; }, 3000);
}

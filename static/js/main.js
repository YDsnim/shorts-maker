/* =====================================================
   main.js — 숏츠 메이커 (비주얼 크롭 UI)
   ===================================================== */

// ── 전역 상태 ────────────────────────────────────────
let uploadedFilename = null;
let originalBase     = null;   // 다운로드 파일명용 원본 베이스
let videoDim = { w: 0, h: 0 };   // 실제 영상 픽셀 크기
let cropPx   = { x: 0, y: 0, w: 0, h: 0 };  // 크롭 영역 (실제 픽셀)
const MIN_PX = 20;  // 크롭 박스 최소 크기

// ── DOM 참조 ─────────────────────────────────────────
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
   업로드
   ==================================================== */
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
  if (file.size > 500 * 1024 * 1024) { showToast('파일이 500MB를 초과합니다.', 'error'); return; }

  dropZone.innerHTML = `<strong>업로드 중...</strong><p>${file.name}</p>`;

  const form = new FormData();
  form.append('video', file);

  try {
    const res  = await fetch('/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!data.ok) { showToast(data.error || '업로드 실패', 'error'); resetDrop(); return; }

    uploadedFilename = data.filename;
    originalBase     = data.original_base || 'video';

    dropZone.innerHTML = `
      <strong>✅ ${file.name}</strong>
      <p style="color:var(--success)">업로드 완료 · 다시 클릭하면 교체</p>
    `;

    // 비디오 정보 표시
    const info = data.info || {};
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    // 크롭 UI 초기화
    initCropUI(data.filename, info);
    showToast('업로드 완료!', 'success');

  } catch { showToast('네트워크 오류', 'error'); resetDrop(); }
}

/* ====================================================
   크롭 UI 초기화
   ==================================================== */
function initCropUI(filename, info) {
  videoDim = { w: info.width || 1280, h: info.height || 720 };

  // 비디오 미리보기 소스 설정
  previewVideo.src = `/uploads/${filename}`;
  previewVideo.currentTime = 0;

  // 비디오 로드 완료 후 크롭 박스 초기 위치 설정
  previewVideo.addEventListener('loadedmetadata', () => {
    initCropBox();
    cropCard.style.display  = 'block';
    actionCard.style.display = 'block';
    // 9:16 여부 감지
    const ratio = videoDim.w / videoDim.h;
    const is916 = Math.abs(ratio - 9 / 16) < 0.01;
    ratioBadge.style.display = is916 ? 'block' : 'none';
  }, { once: true });
}

function initCropBox() {
  const vw = videoDim.w, vh = videoDim.h;
  const ratio = vw / vh;
  const target = 9 / 16;

  if (ratio > target + 0.01) {
    // 가로가 더 넓은 경우 → 9:16 크롭 박스를 가운데에 초기 배치
    const cw = Math.round(vh * target);
    const cx = Math.round((vw - cw) / 2);
    cropPx = { x: cx, y: 0, w: cw, h: vh };
    lock916.checked = true;  // 9:16 잠금 자동 활성화
  } else {
    // 이미 세로이거나 9:16인 경우 → 전체 선택
    cropPx = { x: 0, y: 0, w: vw, h: vh };
  }

  renderCropBox();
}

/* ====================================================
   크롭 박스 렌더 (픽셀 → 화면 좌표 변환)
   ==================================================== */
function renderCropBox() {
  // 컨테이너 실제 표시 크기 계산
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;

  const scaleX = displayW / videoDim.w;
  const scaleY = displayH / videoDim.h;

  cropBox.style.left   = (cropPx.x * scaleX) + 'px';
  cropBox.style.top    = (cropPx.y * scaleY) + 'px';
  cropBox.style.width  = (cropPx.w * scaleX) + 'px';
  cropBox.style.height = (cropPx.h * scaleY) + 'px';

  // 치수 텍스트 업데이트
  const w = Math.round(cropPx.w);
  const h = Math.round(cropPx.h);
  const r = (w / h).toFixed(2);
  cropDims.textContent = `결과: ${w} × ${h} px  (${r} : 1)`;
}

// 창 크기 변경 시 재렌더
window.addEventListener('resize', () => { if (uploadedFilename) renderCropBox(); });

/* ====================================================
   드래그 핸들 이벤트
   ==================================================== */
let drag = null; // { dir, startCX, startCY, startCrop }

// 핸들 각각에 이벤트 등록
cropBox.querySelectorAll('.handle').forEach(handle => {
  handle.addEventListener('mousedown',  e => startDrag(e, handle.dataset.dir));
  handle.addEventListener('touchstart', e => startDrag(e, handle.dataset.dir), { passive: false });
});

// 크롭 박스 자체 클릭 → 이동(move)
cropBox.addEventListener('mousedown',  e => { if (e.target === cropBox) startDrag(e, 'move'); });
cropBox.addEventListener('touchstart', e => { if (e.target === cropBox) startDrag(e, 'move'); }, { passive: false });

function startDrag(e, dir) {
  e.preventDefault();
  e.stopPropagation();
  const pt = getPoint(e);
  drag = { dir, startCX: pt.x, startCY: pt.y, startCrop: { ...cropPx } };
}

document.addEventListener('mousemove',  onDragMove);
document.addEventListener('touchmove',  onDragMove, { passive: false });
document.addEventListener('mouseup',    () => { drag = null; });
document.addEventListener('touchend',   () => { drag = null; });

function onDragMove(e) {
  if (!drag) return;
  e.preventDefault();

  const pt = getPoint(e);
  // 마우스/터치 이동량을 실제 영상 픽셀로 변환
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;
  const dvx = (pt.x - drag.startCX) / displayW  * videoDim.w;
  const dvy = (pt.y - drag.startCY) / displayH * videoDim.h;

  const sc   = drag.startCrop;
  const lock = lock916.checked;
  let { x, y, w, h } = sc;

  switch (drag.dir) {
    // ── 이동 ───────────────────────────────────────
    case 'move':
      x = clamp(sc.x + dvx, 0, videoDim.w - sc.w);
      y = clamp(sc.y + dvy, 0, videoDim.h - sc.h);
      break;

    // ── 위쪽 핸들 ──────────────────────────────────
    case 'n': {
      const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      h = sc.h - (ny - sc.y);
      y = ny;
      if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    // ── 아래쪽 핸들 ────────────────────────────────
    case 's': {
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    // ── 오른쪽 핸들 ────────────────────────────────
    case 'e': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      if (lock) { h = w * (16/9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    // ── 왼쪽 핸들 ──────────────────────────────────
    case 'w': {
      const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      w = sc.w - (nx - sc.x);
      x = nx;
      if (lock) { h = w * (16/9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    // ── 모서리 핸들들 ──────────────────────────────
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

  // 비디오 범위를 벗어나지 않게 보정
  w = clamp(w, MIN_PX, videoDim.w);
  h = clamp(h, MIN_PX, videoDim.h);
  x = clamp(x, 0, videoDim.w - w);
  y = clamp(y, 0, videoDim.h - h);

  cropPx = { x, y, w, h };
  renderCropBox();
}

/* ====================================================
   초기화 버튼
   ==================================================== */
resetBtn.addEventListener('click', initCropBox);

/* ====================================================
   처리 (크롭 적용)
   ==================================================== */
processBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  processBtn.disabled    = true;
  resultSec.style.display = 'none';
  progressSec.style.display = 'block';

  try {
    const res  = await fetch('/process', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename:      uploadedFilename,
        original_base: originalBase,
        crop: {
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

    // 크롭 완료 후 원본은 output/ 으로 이동됐으므로 filename 갱신
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
   유틸리티
   ==================================================== */
function clamp(v, min, max) { return Math.min(Math.max(v, min), max); }

function getPoint(e) {
  if (e.touches && e.touches.length) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
  return { x: e.clientX, y: e.clientY };
}

function resetDrop() {
  dropZone.innerHTML = `<strong>영상을 여기에 끌어다 놓거나 클릭하세요</strong><p>MP4, MOV, AVI, MKV, WebM · 최대 500MB</p>`;
}

/* ====================================================
   대본 추출 (Whisper STT → SRT)
   ==================================================== */
transcribeBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  transcribeBtn.disabled   = true;
  transcribeSec.style.display = 'block';

  try {
    const res  = await fetch('/transcribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: uploadedFilename, original_base: originalBase }),
    });
    const data = await res.json();

    transcribeSec.style.display = 'none';

    if (!data.ok) { showToast(data.error || '대본 추출 실패', 'error'); return; }

    // SRT 파일 즉시 다운로드
    const a = document.createElement('a');
    a.href     = `/download/${data.srt}`;
    a.download = data.srt;
    a.click();
    showToast('대본 추출 완료!', 'success');

  } catch {
    transcribeSec.style.display = 'none';
    showToast('오류가 발생했습니다.', 'error');
  } finally {
    transcribeBtn.disabled = false;
  }
});

/* ====================================================
   YouTube 가져오기
   ==================================================== */
ytBtn.addEventListener('click', fetchYoutube);
ytUrl.addEventListener('keydown', e => { if (e.key === 'Enter') fetchYoutube(); });

async function fetchYoutube() {
  const url = ytUrl.value.trim();
  if (!url) return;

  ytBtn.disabled = true;
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

let toastTimer;
function showToast(msg, type = '') {
  clearTimeout(toastTimer);
  toast.textContent  = msg;
  toast.className    = 'show ' + type;
  toastTimer = setTimeout(() => { toast.className = ''; }, 3000);
}

/* =====================================================
   main.js — 숏츠 메이커

   역할:
     · 파일 업로드 (XHR — 진행률 % 실시간 표시)
     · YouTube URL 가져오기
     · 영역 선택 박스 (항상 표시, 드래그 UI)
     · 배경 선택: 없음(크롭만) / 블러 / 단색
     · 블러·단색 선택 시 서버 프리뷰 (/preview → JPEG)
     · 처리: /process → job_id → SSE 진행률 구독
     · 대본 추출: /transcribe → job_id → SSE 단계 표시
   ===================================================== */

// ── 전역 상태 ────────────────────────────────────────
let uploadedFilename = null;   // 서버 UUID 파일명 (예: a3f9c1d2.mp4)
let originalBase     = null;   // 결과 파일명에 쓸 원본 베이스 (예: '여름휴가')
let videoDim = { w: 0, h: 0 }; // 실제 영상 픽셀 크기 (크롭 좌표 계산 기준)
let cropPx   = { x: 0, y: 0, w: 0, h: 0 };  // 크롭 영역 (픽셀 단위)
let bgMode   = 'none';         // 배경 처리 모드: 'none' | 'blur' | 'solid'
let blurLevel   = 20;          // 블러 강도 (0~40)
let solidColor  = '000000';    // 단색 배경 색상 (hex, # 없이)
const MIN_PX = 20;             // 크롭 박스 최소 픽셀 크기

// ── DOM 참조 ─────────────────────────────────────────
const ytUrl              = document.getElementById('yt-url');
const ytBtn              = document.getElementById('yt-btn');
const dropZone           = document.getElementById('drop-zone');
const uploadProgressWrap = document.getElementById('upload-progress-wrap');
const uploadProgressFill = document.getElementById('upload-progress-fill');
const fileInput          = document.getElementById('file-input');
const editCard           = document.getElementById('edit-card');
const actionCard         = document.getElementById('action-card');
const cropContainer      = document.getElementById('crop-container');
const previewVideo       = document.getElementById('preview-video');
const cropBox            = document.getElementById('crop-box');
const lock916            = document.getElementById('lock-916');
const resetBtn           = document.getElementById('reset-btn');
const processBtn         = document.getElementById('process-btn');
const transcribeBtn      = document.getElementById('transcribe-btn');
const progressSec        = document.getElementById('progress-section');
const progressFill       = document.getElementById('progress-fill');
const progressText       = document.getElementById('progress-text');
const resultSec          = document.getElementById('result-section');
const cropDims           = document.getElementById('crop-dims');
const ratioBadge         = document.getElementById('ratio-badge');
const blurSlider         = document.getElementById('blur-slider');
const blurValueEl        = document.getElementById('blur-value');
const blurPreviewBtn     = document.getElementById('blur-preview-btn');
const solidColorPicker   = document.getElementById('solid-color-picker');
const solidPreviewBtn    = document.getElementById('solid-preview-btn');
const solidColorLabel    = document.getElementById('solid-color-label');
const previewWrap        = document.getElementById('preview-wrap');
const previewImg         = document.getElementById('preview-img');
const toast              = document.getElementById('toast');

/* ====================================================
   업로드 — XHR (진행률 % 실시간 표시)

   fetch()는 업로드 진행률을 알 수 없으므로 XHR을 사용한다.
   xhr.upload.onprogress 이벤트로 전송된 바이트 수를 받아 % 계산.
   ==================================================== */
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover',  e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) uploadFile(fileInput.files[0]); });

function uploadFile(file) {
  if (file.size > 500 * 1024 * 1024) { showToast('파일이 500MB를 초과합니다.', 'error'); return; }

  dropZone.innerHTML = `<strong>업로드 중... 0%</strong><p>${file.name}</p>`;
  uploadProgressWrap.style.display = 'block';
  uploadProgressFill.style.width   = '0%';

  const form = new FormData();
  form.append('video', file);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/upload');

  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      dropZone.querySelector('strong').textContent = `업로드 중... ${pct}%`;
      uploadProgressFill.style.width = pct + '%';
    }
  };

  xhr.onload = () => {
    uploadProgressWrap.style.display = 'none';
    let data;
    try { data = JSON.parse(xhr.responseText); } catch { showToast('서버 오류', 'error'); resetDrop(); return; }

    if (!data.ok) { showToast(data.error || '업로드 실패', 'error'); resetDrop(); return; }

    uploadedFilename = data.filename;
    originalBase     = data.original_base || 'video';

    dropZone.innerHTML = `
      <strong>✅ ${file.name}</strong>
      <p style="color:var(--success)">업로드 완료 · 다시 클릭하면 교체</p>
    `;

    const info = data.info || {};
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    initCropUI(data.filename, info);
    showToast('업로드 완료!', 'success');
  };

  xhr.onerror = () => {
    uploadProgressWrap.style.display = 'none';
    showToast('네트워크 오류', 'error');
    resetDrop();
  };

  xhr.send(form);
}

/* ====================================================
   크롭 UI 초기화
   ==================================================== */
function initCropUI(filename, info) {
  // 새 영상 로드 전 이전 상태 초기화
  editCard.style.display    = 'none';
  actionCard.style.display  = 'none';
  previewWrap.style.display = 'none';
  cropPx = { x: 0, y: 0, w: 0, h: 0 };

  videoDim = { w: info.width || 1280, h: info.height || 720 };

  previewVideo.src = `/uploads/${encodeURIComponent(filename)}`;

  previewVideo.addEventListener('loadedmetadata', () => {
    // 카드를 먼저 표시해야 cropContainer.offsetWidth가 0이 아닌 실제 값을 반환함
    editCard.style.display   = 'block';
    actionCard.style.display = 'flex';
    previewWrap.style.display = 'none';

    const ratio = videoDim.w / videoDim.h;
    ratioBadge.style.display = Math.abs(ratio - 9 / 16) < 0.01 ? 'block' : 'none';

    // 검정 인트로 프레임 건너뜀: 5% 또는 최대 3초
    previewVideo.currentTime = Math.min(previewVideo.duration * 0.05, 3);
    initCropBox();
  }, { once: true });
}

function initCropBox() {
  const vw = videoDim.w, vh = videoDim.h;
  const ratio  = vw / vh;
  const target = 9 / 16;

  let cw, ch;
  if (ratio > target + 0.01) {
    // 가로 영상: 높이 기준으로 9:16 박스
    ch = vh;
    cw = Math.round(ch * target);
    lock916.checked = true;
  } else {
    // 세로/정방형 영상: 너비 기준으로 9:16 박스
    cw = vw;
    ch = Math.round(cw / target);
    lock916.checked = false;
  }

  // ffmpeg 요구: 2의 배수
  cw -= cw % 2;
  ch -= ch % 2;

  // 가로·세로 모두 중앙 배치
  cropPx = {
    x: Math.round((vw - cw) / 2),
    y: Math.round((vh - ch) / 2),
    w: cw,
    h: ch,
  };

  renderCropBox();
}

/* ====================================================
   크롭 박스 렌더 (픽셀 좌표 → 화면 CSS 좌표 변환)
   ==================================================== */
function renderCropBox() {
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;
  const scaleX   = displayW / videoDim.w;
  const scaleY   = displayH / videoDim.h;

  cropBox.style.left   = (cropPx.x * scaleX) + 'px';
  cropBox.style.top    = (cropPx.y * scaleY) + 'px';
  cropBox.style.width  = (cropPx.w * scaleX) + 'px';
  cropBox.style.height = (cropPx.h * scaleY) + 'px';

  const w = Math.round(cropPx.w);
  const h = Math.round(cropPx.h);
  cropDims.textContent = `결과: ${w} × ${h} px  (${(w / h).toFixed(2)} : 1)`;
}

window.addEventListener('resize', () => { if (uploadedFilename) renderCropBox(); });

/* ====================================================
   드래그 핸들 이벤트
   ==================================================== */
let drag = null;

cropBox.querySelectorAll('.handle').forEach(handle => {
  handle.addEventListener('mousedown',  e => startDrag(e, handle.dataset.dir));
  handle.addEventListener('touchstart', e => startDrag(e, handle.dataset.dir), { passive: false });
});
cropBox.addEventListener('mousedown',  e => { if (e.target === cropBox) startDrag(e, 'move'); });
cropBox.addEventListener('touchstart', e => { if (e.target === cropBox) startDrag(e, 'move'); }, { passive: false });

function startDrag(e, dir) {
  e.preventDefault();
  e.stopPropagation();
  const pt = getPoint(e);
  drag = { dir, startCX: pt.x, startCY: pt.y, startCrop: { ...cropPx } };
}

document.addEventListener('mousemove', onDragMove);
document.addEventListener('touchmove', onDragMove, { passive: false });
document.addEventListener('mouseup',   () => { drag = null; });
document.addEventListener('touchend',  () => { drag = null; });

function onDragMove(e) {
  if (!drag) return;
  e.preventDefault();

  const pt       = getPoint(e);
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;
  const dvx = (pt.x - drag.startCX) / displayW  * videoDim.w;
  const dvy = (pt.y - drag.startCY) / displayH * videoDim.h;

  const sc   = drag.startCrop;
  const lock = lock916.checked;
  let { x, y, w, h } = sc;

  switch (drag.dir) {
    case 'move':
      x = clamp(sc.x + dvx, 0, videoDim.w - sc.w);
      y = clamp(sc.y + dvy, 0, videoDim.h - sc.h);
      break;
    case 'n': {
      const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      h = sc.h - (ny - sc.y); y = ny;
      if (lock) { w = h * (9 / 16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    case 's': {
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { w = h * (9 / 16); x = clamp(sc.x + (sc.w - w) / 2, 0, videoDim.w - w); }
      break;
    }
    case 'e': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      if (lock) { h = w * (16 / 9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    case 'w': {
      const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      w = sc.w - (nx - sc.x); x = nx;
      if (lock) { h = w * (16 / 9); y = clamp(sc.y + (sc.h - h) / 2, 0, videoDim.h - h); }
      break;
    }
    case 'nw': {
      const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      w = sc.w - (nx - sc.x); h = sc.h - (ny - sc.y); x = nx; y = ny;
      if (lock) { h = w * (16 / 9); y = sc.y + sc.h - h; }
      break;
    }
    case 'ne': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      const ny2 = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX);
      h = sc.h - (ny2 - sc.y); y = ny2;
      if (lock) { h = w * (16 / 9); y = sc.y + sc.h - h; }
      break;
    }
    case 'sw': {
      const nx2 = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX);
      w = sc.w - (nx2 - sc.x); x = nx2;
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { h = w * (16 / 9); }
      break;
    }
    case 'se': {
      w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x);
      h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y);
      if (lock) { h = w * (16 / 9); }
      break;
    }
  }

  w = clamp(w, MIN_PX, videoDim.w);
  h = clamp(h, MIN_PX, videoDim.h);
  x = clamp(x, 0, videoDim.w - w);
  y = clamp(y, 0, videoDim.h - h);

  cropPx = { x, y, w, h };
  renderCropBox();
}

resetBtn.addEventListener('click', initCropBox);

lock916.addEventListener('change', () => {
  if (!lock916.checked) return;

  let w = cropPx.w;
  let h = Math.round(w * 16 / 9);

  if (h > videoDim.h) {
    h = videoDim.h;
    w = Math.round(h * 9 / 16);
  }

  w -= w % 2;
  h -= h % 2;

  const y = Math.min(cropPx.y, videoDim.h - h);
  cropPx = { x: cropPx.x, y, w, h };
  renderCropBox();
});

/* ====================================================
   배경 모드 선택
   ==================================================== */
document.querySelectorAll('.bg-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    bgMode = btn.dataset.bg;
    document.querySelectorAll('.bg-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');

    document.getElementById('blur-controls').style.display  = bgMode === 'blur'  ? 'block' : 'none';
    document.getElementById('solid-controls').style.display = bgMode === 'solid' ? 'block' : 'none';
    previewWrap.style.display = 'none';

    updateProcessLabel();
  });
});

function updateProcessLabel() {
  const labels = {
    none:  '✂️ 크롭 적용',
    blur:  '🌫 블러 배경 적용',
    solid: '🎨 단색 배경 적용',
  };
  processBtn.textContent = labels[bgMode];
}

/* ====================================================
   블러 패널 — 강도 슬라이더
   ==================================================== */
blurSlider.addEventListener('input', () => {
  blurLevel = parseInt(blurSlider.value, 10);
  blurValueEl.textContent = blurLevel;
});

blurPreviewBtn.addEventListener('click', () => requestPreview());

/* ====================================================
   단색 패널 — 색상 프리셋 + 피커
   ==================================================== */
const COLOR_NAMES = {
  '000000': '검정', 'ffffff': '흰색', '1a1a2e': '딥 블루',
  '2d1b69': '퍼플', '0f3460': '다크 블루', '16213e': '네이비',
};

function selectColor(hex) {
  solidColor = hex.replace('#', '').toLowerCase();
  solidColorPicker.value    = '#' + solidColor;
  solidColorLabel.textContent = `선택: ${COLOR_NAMES[solidColor] || '사용자 지정'} (#${solidColor})`;
  document.querySelectorAll('.color-preset').forEach(b => {
    b.classList.toggle('active', b.dataset.color === solidColor);
  });
}

document.querySelectorAll('.color-preset').forEach(btn => {
  btn.addEventListener('click', () => selectColor(btn.dataset.color));
});

solidColorPicker.addEventListener('input', () => selectColor(solidColorPicker.value));

solidPreviewBtn.addEventListener('click', () => requestPreview());

/* ====================================================
   서버 프리뷰 요청

   블러·단색 배경 선택 시 "미리보기" 버튼을 누르면 호출된다.
   항상 현재 선택된 cropPx 좌표를 함께 전송하므로
   "영역 선택 + 배경"이 합쳐진 결과를 미리 볼 수 있다.
   ==================================================== */
async function requestPreview() {
  if (!uploadedFilename) { showToast('먼저 영상을 올려주세요.', 'error'); return; }

  const btn = bgMode === 'blur' ? blurPreviewBtn : solidPreviewBtn;
  const origText  = btn.textContent;
  btn.disabled    = true;
  btn.textContent = '⏳ 생성 중...';

  const body = {
    filename:  uploadedFilename,
    bg_mode:   bgMode,
    seek_time: previewVideo.currentTime,
    crop: {
      x: Math.round(cropPx.x), y: Math.round(cropPx.y),
      w: Math.round(cropPx.w), h: Math.round(cropPx.h),
    },
  };
  if (bgMode === 'blur')  body.blur  = blurLevel;
  else                    body.color = solidColor;

  try {
    const res = await fetch('/preview', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });

    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      showToast(j.error || '프리뷰 생성 실패', 'error');
      return;
    }

    const blob = await res.blob();
    if (previewImg.src && previewImg.src.startsWith('blob:')) URL.revokeObjectURL(previewImg.src);
    previewImg.src            = URL.createObjectURL(blob);
    previewWrap.style.display = 'block';

  } catch { showToast('프리뷰 오류', 'error'); }
  finally {
    btn.disabled    = false;
    btn.textContent = origText;
  }
}

/* ====================================================
   처리 (크롭·블러·단색 적용)
   ==================================================== */
processBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  processBtn.disabled     = true;
  resultSec.style.display = 'none';
  showProgress('처리 시작 중...', 0);

  const body = {
    filename:      uploadedFilename,
    original_base: originalBase,
    bg_mode:       bgMode,
    crop: {
      x: Math.round(cropPx.x), y: Math.round(cropPx.y),
      w: Math.round(cropPx.w), h: Math.round(cropPx.h),
    },
  };
  if (bgMode === 'blur')  body.blur  = blurLevel;
  if (bgMode === 'solid') body.color = solidColor;

  try {
    const res  = await fetch('/process', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    const data = await res.json();

    if (!data.ok) {
      showToast(data.error || '처리 실패', 'error');
      hideProgress();
      processBtn.disabled = false;
      return;
    }

    subscribeProgress(data.job_id, payload => {
      if (payload.error) {
        showToast(payload.error, 'error');
        hideProgress();
        processBtn.disabled = false;
        return;
      }

      updateProgress(payload.pct, payload.msg || '처리 중...');

      if (payload.done) {
        hideProgress();
        const dlBtn = document.getElementById('download-btn');
        dlBtn.href     = `/download/${encodeURIComponent(payload.result)}`;
        dlBtn.download = payload.result;
        resultSec.style.display = 'block';
        processBtn.disabled = false;
        showToast('완성! 다운로드 버튼을 눌러주세요.', 'success');
      }
    });

  } catch {
    hideProgress();
    processBtn.disabled = false;
    showToast('오류가 발생했습니다.', 'error');
  }
});

/* ====================================================
   대본 추출 (Whisper STT → SRT)
   ==================================================== */
transcribeBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;

  transcribeBtn.disabled = true;
  showProgress('대본 추출 준비 중...', 0);

  try {
    const res  = await fetch('/transcribe', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ filename: uploadedFilename, original_base: originalBase }),
    });
    const data = await res.json();

    if (!data.ok) {
      showToast(data.error || '대본 추출 실패', 'error');
      hideProgress();
      transcribeBtn.disabled = false;
      return;
    }

    subscribeProgress(data.job_id, payload => {
      if (payload.error) {
        showToast(payload.error, 'error');
        hideProgress();
        transcribeBtn.disabled = false;
        return;
      }

      updateProgress(payload.pct, payload.msg || '대본 추출 중...');

      if (payload.done && payload.srt) {
        hideProgress();
        const a = document.createElement('a');
        a.href     = `/download/${encodeURIComponent(payload.srt)}`;
        a.download = payload.srt;
        a.click();
        showToast('대본 추출 완료!', 'success');
        transcribeBtn.disabled = false;
      }
    });

  } catch {
    hideProgress();
    transcribeBtn.disabled = false;
    showToast('오류가 발생했습니다.', 'error');
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

  ytBtn.disabled    = true;
  ytBtn.textContent = '⏳ 다운로드 중...';
  dropZone.innerHTML = `<strong>YouTube 영상 다운로드 중...</strong><p>${url}</p>`;

  try {
    const res  = await fetch('/fetch-youtube', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!data.ok) { showToast(data.error || '다운로드 실패', 'error'); resetDrop(); return; }

    uploadedFilename = data.filename;
    originalBase     = data.original_base || 'video';

    const info = data.info || {};
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    dropZone.innerHTML = `
      <strong>✅ ${data.original_base}</strong>
      <p style="color:var(--success)">${info.duration_str ? info.duration_str + ' · ' : ''}${info.width ? info.width + '×' + info.height : ''}</p>
      <button class="btn" id="go-edit-btn" style="margin-top:12px">✂️ 편집 시작</button>
      <p style="font-size:.8rem;color:var(--muted);margin-top:6px">다른 영상으로 교체하려면 파일을 업로드하거나 URL을 다시 입력하세요</p>
    `;
    document.getElementById('go-edit-btn').addEventListener('click', e => {
      e.stopPropagation();
      initCropUI(data.filename, info);
    });

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
   SSE 진행률 구독 헬퍼
   ==================================================== */
function subscribeProgress(jobId, onData) {
  const es = new EventSource(`/progress/${jobId}`);

  es.onmessage = e => {
    let payload;
    try { payload = JSON.parse(e.data); } catch { return; }
    onData(payload);
    if (payload.done || payload.error) es.close();
  };

  es.onerror = () => {
    es.close();
    onData({ done: true, error: '연결 오류가 발생했습니다.' });
  };
}

/* ====================================================
   진행 바 헬퍼
   ==================================================== */
function showProgress(msg, pct) {
  progressSec.style.display = 'block';
  progressText.textContent  = msg || '처리 중...';
  if (!pct) {
    progressFill.classList.add('indeterminate');
    progressFill.style.width = '';
  } else {
    progressFill.classList.remove('indeterminate');
    progressFill.style.width = pct + '%';
  }
}

function updateProgress(pct, msg) {
  if (pct > 0) {
    progressFill.classList.remove('indeterminate');
    progressFill.style.width = pct + '%';
  }
  if (msg) progressText.textContent = msg;
}

function hideProgress() {
  progressSec.style.display = 'none';
  progressFill.classList.remove('indeterminate');
  progressFill.style.width  = '0%';
}

/* ====================================================
   유틸리티 함수
   ==================================================== */
function clamp(v, min, max) { return Math.min(Math.max(v, min), max); }

function getPoint(e) {
  if (e.touches && e.touches.length) return { x: e.touches[0].clientX, y: e.touches[0].clientY };
  return { x: e.clientX, y: e.clientY };
}

function resetDrop() {
  dropZone.innerHTML = `<strong>영상을 여기에 끌어다 놓거나 클릭하세요</strong><p>MP4, MOV, AVI, MKV, WebM · 최대 500MB</p>`;
  uploadProgressWrap.style.display = 'none';
  uploadProgressFill.style.width   = '0%';
}

let toastTimer;
function showToast(msg, type = '') {
  clearTimeout(toastTimer);
  toast.textContent = msg;
  toast.className   = 'show ' + type;
  toastTimer = setTimeout(() => { toast.className = ''; }, 3000);
}

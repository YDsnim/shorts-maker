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
const previewImgs        = [1, 2, 3].map(i => document.getElementById(`preview-img-${i}`));
const previewLabels      = [1, 2, 3].map(i => document.getElementById(`preview-label-${i}`));
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

  // 새 파일 선택 시 이전 편집 상태 즉시 초기화
  editCard.style.display    = 'none';
  actionCard.style.display  = 'none';
  previewWrap.style.display = 'none';
  progressSec.style.display = 'none';
  resultSec.style.display   = 'none';
  cropPx = { x: 0, y: 0, w: 0, h: 0 };

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
function fmtTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

async function requestPreview() {
  if (!uploadedFilename) { showToast('먼저 영상을 올려주세요.', 'error'); return; }

  const btn = bgMode === 'blur' ? blurPreviewBtn : solidPreviewBtn;
  const origText  = btn.textContent;
  btn.disabled    = true;
  btn.textContent = '⏳ 생성 중...';

  const dur = previewVideo.duration || 10;
  const seekTimes = [dur * 0.2, dur * 0.5, dur * 0.8];

  const makeBody = (seekTime) => {
    const body = {
      filename:  uploadedFilename,
      bg_mode:   bgMode,
      seek_time: seekTime,
      crop: {
        x: Math.round(cropPx.x), y: Math.round(cropPx.y),
        w: Math.round(cropPx.w), h: Math.round(cropPx.h),
      },
    };
    if (bgMode === 'blur')  body.blur  = blurLevel;
    else                    body.color = solidColor;
    return body;
  };

  try {
    const results = await Promise.all(seekTimes.map(t =>
      fetch('/preview', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(makeBody(t)),
      })
    ));

    for (const res of results) {
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        showToast(j.error || '프리뷰 생성 실패', 'error');
        return;
      }
    }

    const blobs = await Promise.all(results.map(r => r.blob()));
    blobs.forEach((blob, i) => {
      if (previewImgs[i].src && previewImgs[i].src.startsWith('blob:')) URL.revokeObjectURL(previewImgs[i].src);
      previewImgs[i].src     = URL.createObjectURL(blob);
      previewLabels[i].textContent = fmtTime(seekTimes[i]);
    });
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

  // 새 영상 다운로드 시작 시 이전 편집 상태 즉시 초기화
  editCard.style.display    = 'none';
  actionCard.style.display  = 'none';
  previewWrap.style.display = 'none';
  progressSec.style.display = 'none';
  resultSec.style.display   = 'none';
  cropPx = { x: 0, y: 0, w: 0, h: 0 };

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

/* ====================================================
   페이지 로드 시 파이프라인 설정 상태 확인
   ==================================================== */
checkPipelineConfig();

/* ====================================================
   메인 소스 영상 업로드 + 템플릿 미리보기
   ==================================================== */
let sourceFilename = null;

const sourceDropZone    = document.getElementById('source-drop-zone');
const sourceFileInput   = document.getElementById('source-file-input');
const sourceUploadProg  = document.getElementById('source-upload-progress');
const sourceUploadFill  = document.getElementById('source-upload-fill');
const sourceUploadText  = document.getElementById('source-upload-text');
const sourcePreviewWrap = document.getElementById('source-preview-wrap');
const sourcePreviewImg  = document.getElementById('source-preview-img');
const sourceFilenameLabel = document.getElementById('source-filename-label');
const sourceRefreshBtn  = document.getElementById('source-refresh-btn');

sourceDropZone.addEventListener('click', () => sourceFileInput.click());
sourceDropZone.addEventListener('dragover', e => {
  e.preventDefault();
  sourceDropZone.classList.add('drag-over');
});
sourceDropZone.addEventListener('dragleave', () => sourceDropZone.classList.remove('drag-over'));
sourceDropZone.addEventListener('drop', e => {
  e.preventDefault();
  sourceDropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) uploadSourceFile(f);
});
sourceFileInput.addEventListener('change', () => {
  if (sourceFileInput.files[0]) uploadSourceFile(sourceFileInput.files[0]);
  sourceFileInput.value = '';
});

function uploadSourceFile(file) {
  const fd = new FormData();
  fd.append('file', file);

  sourceUploadProg.style.display  = 'block';
  sourcePreviewWrap.style.display = 'none';
  sourceUploadFill.style.width    = '0%';
  sourceUploadText.textContent    = '업로드 중...';

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/pipeline/upload-source');

  xhr.upload.onprogress = e => {
    if (e.lengthComputable) {
      const pct = Math.round(e.loaded / e.total * 100);
      sourceUploadFill.style.width = pct + '%';
      sourceUploadText.textContent = `업로드 중... ${pct}%`;
    }
  };

  xhr.onload = async () => {
    if (xhr.status === 200) {
      const data = JSON.parse(xhr.responseText);
      if (data.ok) {
        sourceFilename = data.filename;
        sourceFilenameLabel.textContent = file.name;
        sourceUploadText.textContent    = '미리보기 생성 중...';
        await requestTemplatePreview();
        sourceUploadProg.style.display  = 'none';
      } else {
        sourceUploadText.textContent = '업로드 실패: ' + data.error;
      }
    } else {
      sourceUploadText.textContent = '업로드 실패';
    }
  };

  xhr.onerror = () => { sourceUploadText.textContent = '업로드 오류'; };
  xhr.send(fd);
}

/* ====================================================
   레이아웃 위치 + 폰트 크기 조정
   ==================================================== */

// data-key → hidden input ID
const POS_INPUT = {
  banner_h:       'pos-banner-h',
  video_y_namnam: 'pos-video-y-namnam',
  title_y:        'pos-title-y',
  video_y_silver: 'pos-video-y-silver',
  subtitle_y:     'pos-subtitle-y',
  source_y:       'pos-source-y',
};
// data-key → y값 표시 span ID
const POS_YSPAN = {
  banner_h:       'dhv-banner-h',
  video_y_namnam: 'dhv-video-y-nm',
  title_y:        'dhv-title-y',
  video_y_silver: 'dhv-video-y-sc',
  subtitle_y:     'dhv-subtitle-y',
  source_y:       'dhv-source-y',
};
// data-sty → hidden input ID / 표시 span ID
const STY_INPUT = {
  banner_font_size:   'sty-banner-size',
  title_font_size:    'sty-title-size',
  subtitle_font_size: 'sty-subtitle-size',
  source_font_size:   'sty-source-size',
};
const STY_SPAN = {
  banner_font_size:   'szn-banner',
  title_font_size:    'szn-title',
  subtitle_font_size: 'szn-subtitle',
  source_font_size:   'szn-source',
};

function posVal(key) {
  return parseInt(document.getElementById(POS_INPUT[key])?.value) || 0;
}
function setPosVal(key, v) {
  const handle = document.querySelector(`.drag-handle[data-key="${key}"]`);
  const min = parseInt(handle?.dataset.min) || 0;
  const max = parseInt(handle?.dataset.max) || 1920;
  v = Math.round(Math.max(min, Math.min(max, v)) / 10) * 10;
  const inp = document.getElementById(POS_INPUT[key]);
  if (inp) inp.value = v;
  const sp  = document.getElementById(POS_YSPAN[key]);
  if (sp)  sp.textContent = v;
  return v;
}

function styVal(key) {
  return parseInt(document.getElementById(STY_INPUT[key])?.value) || 0;
}
function setStyVal(key, v) {
  const min = 12, max = 120;
  v = Math.max(min, Math.min(max, v));
  const inp = document.getElementById(STY_INPUT[key]);
  if (inp) inp.value = v;
  const sp  = document.getElementById(STY_SPAN[key]);
  if (sp)  sp.textContent = v;
  return v;
}

function syncHandlePositions() {
  document.querySelectorAll('.drag-handle').forEach(h => {
    const v = posVal(h.dataset.key);
    h.style.top = (v / 1920 * 100) + '%';
  });
}

// ── 드래그 ──────────────────────────────────────────
let _drag = null;

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.drag-handle').forEach(handle => {
    const onStart = (e) => {
      // sz-btn 클릭은 드래그 무시
      if (e.target.classList.contains('sz-btn')) return;
      e.preventDefault();
      const wrap = document.getElementById('preview-drag-wrap');
      _drag = {
        handle,
        key:    handle.dataset.key,
        rect:   wrap.getBoundingClientRect(),
        startY: e.touches ? e.touches[0].clientY : e.clientY,
        startV: posVal(handle.dataset.key),
      };
    };
    handle.addEventListener('mousedown',  onStart);
    handle.addEventListener('touchstart', onStart, { passive: false });
  });

  // 폰트 크기 +/- 버튼
  document.querySelectorAll('.sz-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const sty   = btn.dataset.sty;
      const delta = parseInt(btn.dataset.delta);
      setStyVal(sty, styVal(sty) + delta);
      if (sourceFilename) debouncedPreview();
    });
  });
});

document.addEventListener('mousemove', (e) => {
  if (!_drag) return;
  const dy = e.clientY - _drag.startY;
  const dv = (dy / _drag.rect.height) * 1920;
  const v  = setPosVal(_drag.key, _drag.startV + dv);
  _drag.handle.style.top = (v / 1920 * 100) + '%';
});
document.addEventListener('touchmove', (e) => {
  if (!_drag) return;
  e.preventDefault();
  const dy = e.touches[0].clientY - _drag.startY;
  const dv = (dy / _drag.rect.height) * 1920;
  const v  = setPosVal(_drag.key, _drag.startV + dv);
  _drag.handle.style.top = (v / 1920 * 100) + '%';
}, { passive: false });

document.addEventListener('mouseup',  () => { if (_drag) { _drag = null; debouncedPreview(); } });
document.addEventListener('touchend', () => { if (_drag) { _drag = null; debouncedPreview(); } });

// ── 값 수집 ─────────────────────────────────────────
function getPositions() {
  const tpl = document.querySelector('input[name="template"]:checked')?.value || 'namnam';
  // subtitle_y → margin_v = 1920 - subtitle_y
  const sub_margin = 1920 - posVal('subtitle_y');
  if (tpl === 'silver_crown') {
    return {
      title_y:          posVal('title_y'),
      video_y:          posVal('video_y_silver'),
      source_y:         posVal('source_y'),
      subtitle_margin_v: sub_margin,
    };
  } else {
    return {
      banner_h:          posVal('banner_h'),
      video_y:           posVal('video_y_namnam'),
      subtitle_margin_v: sub_margin,
    };
  }
}

function getStyles() {
  return {
    banner_font_size:   styVal('banner_font_size'),
    title_font_size:    styVal('title_font_size'),
    subtitle_font_size: styVal('subtitle_font_size'),
    source_font_size:   styVal('source_font_size'),
  };
}

function getSourceText() {
  return document.getElementById('source-text-input')?.value?.trim() || '';
}

// ── 템플릿 전환 ──────────────────────────────────────
function applyTemplateSwitch(tpl) {
  const isSilver = tpl === 'silver_crown';
  document.querySelectorAll('.drag-handle').forEach(h => {
    const forNm = h.dataset.nm === '1';
    const forSc = h.dataset.sc === '1';
    h.style.display = (forNm && !isSilver) || (forSc && isSilver) || (forNm && forSc) ? '' : 'none';
  });
  const stw = document.getElementById('source-text-wrap');
  if (stw) stw.style.display = isSilver ? '' : 'none';
  document.getElementById('tpl-namnam').style.borderColor = isSilver ? 'var(--border)' : 'var(--accent)';
  document.getElementById('tpl-silver').style.borderColor = isSilver ? 'var(--accent)' : 'var(--border)';
}

document.querySelectorAll('input[name="template"]').forEach(radio => {
  radio.addEventListener('change', () => {
    applyTemplateSwitch(radio.value);
    if (sourceFilename) requestTemplatePreview();
  });
});

// 출처 텍스트 변경 → 갱신
document.getElementById('source-text-input')?.addEventListener('input', () => {
  if (sourceFilename) debouncedPreview();
});

let previewDebounce = null;
function debouncedPreview() {
  clearTimeout(previewDebounce);
  previewDebounce = setTimeout(requestTemplatePreview, 600);
}

async function requestTemplatePreview() {
  if (!sourceFilename) return;
  const tpl   = document.querySelector('input[name="template"]:checked')?.value || 'namnam';
  const title = document.getElementById('topic-input').value.trim();

  try {
    const res  = await fetch('/pipeline/template-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename:    sourceFilename,
        template:    tpl,
        title,
        positions:   getPositions(),
        styles:      getStyles(),
        source_text: getSourceText(),
      }),
    });
    const data = await res.json();
    if (data.ok) {
      sourcePreviewImg.src            = data.preview_url + '?t=' + Date.now();
      sourcePreviewWrap.style.display = 'block';
      sourcePreviewImg.onload = syncHandlePositions;
    } else {
      showToast('미리보기 실패: ' + data.error, 'error');
    }
  } catch (e) {
    showToast('미리보기 오류: ' + e.message, 'error');
  }
}

// 제목 변경 시 자동 갱신
document.getElementById('topic-input').addEventListener('input', () => {
  if (!sourceFilename) return;
  debouncedPreview();
});

// 갱신 버튼
sourceRefreshBtn.addEventListener('click', requestTemplatePreview);

/* ====================================================
   창작 파이프라인 — 상태
   ==================================================== */
let pipelineTopic    = '';   // 현재 주제

// DOM 참조 (창작 모드 전용)
const topicInput          = document.getElementById('topic-input');
const scriptCard          = document.getElementById('script-card');
const scriptTextarea      = document.getElementById('script-textarea');
const approveScriptBtn    = document.getElementById('approve-script-btn');
const downloadScriptBtn   = document.getElementById('download-script-btn');
const pipelineProgressCard = document.getElementById('pipeline-progress-card');
const pipelineFill        = document.getElementById('pipeline-fill');
const pipelineText        = document.getElementById('pipeline-text');
const pipelineResultCard  = document.getElementById('pipeline-result-card');
const pipelineDownloadBtn = document.getElementById('pipeline-download-btn');
const srtDownloadBtn      = document.getElementById('srt-download-btn');
const srtPreview          = document.getElementById('srt-preview');
const srtContent          = document.getElementById('srt-content');
const pipelineNewBtn      = document.getElementById('pipeline-new-btn');
const pipelineEta         = document.getElementById('pipeline-eta');
const apiWarning          = document.getElementById('api-warning');
const uploadScriptBtn     = document.getElementById('upload-script-btn');
const scriptFileInput     = document.getElementById('script-file-input');

// 단계 인디케이터 요소
const PSTEPS = {
  voice:    document.getElementById('pstep-voice'),
  bg:       document.getElementById('pstep-bg'),
  sub:      document.getElementById('pstep-sub'),
  assemble: document.getElementById('pstep-assemble'),
};

/* ====================================================
   이라스토야 태그 파싱 + 이미지 선택 UI
   ==================================================== */
// 태그 형식: (keyword:N초) 또는 (keyword:Ns)
const IRA_TAG_RE = /\(([^():]+):(\d+(?:\.\d+)?)[초s]\)/g;

function parseScriptTags(script) {
  const tags = [];
  IRA_TAG_RE.lastIndex = 0;
  let match;
  while ((match = IRA_TAG_RE.exec(script)) !== null) {
    const beforeTag = script.substring(0, match.index).trimEnd().split('\n').pop().trim();
    tags.push({
      keyword:  match[1].trim(),
      duration: parseFloat(match[2]),
      anchor:   beforeTag,
      original: match[0],
    });
  }
  return tags;
}

function stripScriptTags(script) {
  return script.replace(/\([^():]+:\d+(?:\.\d+)?[초s]\)/g, '').replace(/\s{2,}/g, ' ').trim();
}


/* API 키 설정 상태 확인 */
async function checkPipelineConfig() {
  try {
    const res  = await fetch('/pipeline/check-config');
    const data = await res.json();
    apiWarning.style.display = 'none';
  } catch { /* 네트워크 오류는 무시 */ }
}

/* ====================================================
   대본 업로드 — 파일 내용을 textarea에 표시
   ==================================================== */
uploadScriptBtn.addEventListener('click', () => scriptFileInput.click());

scriptFileInput.addEventListener('change', () => {
  const file = scriptFileInput.files[0];
  if (!file) return;
  const isSrt = file.name.toLowerCase().endsWith('.srt');
  const reader = new FileReader();
  reader.onload = e => {
    const raw = e.target.result.trim();
    scriptTextarea.value = isSrt ? parseSrtToText(raw) : raw;
    showToast(isSrt ? 'SRT에서 텍스트 추출 완료' : '대본 업로드 완료', 'success');
  };
  reader.readAsText(file, 'UTF-8');
  scriptFileInput.value = '';
});

function parseSrtToText(srt) {
  // 번호줄, 타임코드줄 제거 → 텍스트 줄만 추출
  const lines = srt.split('\n');
  const text  = [];
  for (const line of lines) {
    const t = line.trim();
    if (!t) continue;
    if (/^\d+$/.test(t)) continue;                   // 번호
    if (/^\d{2}:\d{2}:\d{2}[,\.]\d{3}/.test(t)) continue; // 타임코드
    text.push(t);
  }
  return text.join(' ');
}

/* ====================================================
   대본 저장 (.txt)
   ==================================================== */
downloadScriptBtn.addEventListener('click', () => {
  const text = scriptTextarea.value.trim();
  if (!text) { showToast('대본이 없습니다.', 'error'); return; }
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = (topicInput.value.trim() || '대본') + '.txt';
  a.click();
  URL.revokeObjectURL(a.href);
});

/* ====================================================
   Step 2: 승인 → 파이프라인 실행
   ==================================================== */
approveScriptBtn.addEventListener('click', async () => {
  const script  = scriptTextarea.value.trim();
  const useTts  = document.getElementById('use-tts-toggle').checked;
  if (!script && useTts) { showToast('TTS 사용 시 대본을 입력해주세요.', 'error'); return; }
  if (!sourceFilename) { showToast('메인 소스 영상을 먼저 업로드해주세요.', 'error'); return; }

  pipelineTopic = topicInput.value.trim() || '숏츠';

  // 바로 실행
  approveScriptBtn.disabled    = true;
  scriptCard.style.display     = 'none';
  pipelineProgressCard.style.display = 'block';
  pipelineResultCard.style.display   = 'none';

  // 단계 인디케이터 초기화
  Object.values(PSTEPS).forEach(el => el.classList.remove('active', 'done'));
  PSTEPS.voice.classList.add('active');
  pipelineFill.style.width = '0%';
  pipelineText.textContent = '준비 중...';
  pipelineEta.textContent   = '진행 중: 0초 경과';
  pipelineEta.style.display = 'block';
  const _pipelineStart = Date.now();
  let _etaTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - _pipelineStart) / 1000);
    const m = Math.floor(sec / 60), s = sec % 60;
    pipelineEta.textContent = m > 0
      ? `진행 중: ${m}분 ${s}초 경과`
      : `진행 중: ${s}초 경과`;
  }, 1000);

  try {
    const res  = await fetch('/pipeline/run', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        script:          stripScriptTags(script),
        topic:           pipelineTopic,
        template:        document.querySelector('input[name="template"]:checked')?.value || 'namnam',
        source_filename: sourceFilename,
        use_tts:         document.getElementById('use-tts-toggle').checked,
        use_subtitle:    document.getElementById('use-subtitle-toggle').checked,
        positions:       getPositions(),
        styles:          getStyles(),
        source_text:     getSourceText(),
      }),
    });
    const data = await res.json();

    if (!data.ok) {
      showToast(data.error || '파이프라인 실행 실패', 'error');
      pipelineProgressCard.style.display = 'none';
      scriptCard.style.display           = 'block';
      approveScriptBtn.disabled          = false;
      return;
    }

    subscribeProgress(data.job_id, payload => {
      if (payload.error) {
        clearInterval(_etaTimer);
        pipelineEta.style.display          = 'none';
        pipelineText.textContent           = '❌ ' + payload.error;
        pipelineProgressCard.style.display = 'none';
        scriptCard.style.display           = 'block';
        approveScriptBtn.disabled          = false;
        showToast('파이프라인 오류', 'error');
        return;
      }

      const pct = payload.pct || 0;
      pipelineFill.style.width = pct + '%';
      if (payload.msg) pipelineText.textContent = payload.msg;

      // 진행률에 따라 단계 인디케이터 업데이트
      _updatePipelineSteps(pct);

      if (payload.done) {
        clearInterval(_etaTimer);
        Object.values(PSTEPS).forEach(el => { el.classList.remove('active'); el.classList.add('done'); });
        pipelineEta.style.display          = 'none';
        pipelineProgressCard.style.display = 'none';
        pipelineResultCard.style.display   = 'block';
        pipelineDownloadBtn.href           = `/download/${payload.result}`;
        pipelineDownloadBtn.download       = payload.result;

        if (payload.srt) {
          srtDownloadBtn.href              = `/download/${payload.srt}`;
          srtDownloadBtn.download          = payload.srt;
          srtDownloadBtn.style.display     = 'block';
          fetch(`/download/${payload.srt}`)
            .then(r => r.text())
            .then(text => {
              srtContent.textContent       = text;
              srtPreview.style.display     = 'block';
            })
            .catch(() => {});
        }

        showToast('숏츠 완성!', 'success');
      }
    });

  } catch {
    clearInterval(_etaTimer);
    pipelineEta.style.display          = 'none';
    showToast('네트워크 오류', 'error');
    pipelineProgressCard.style.display = 'none';
    scriptCard.style.display           = 'block';
    approveScriptBtn.disabled          = false;
  }
});

/* 진행률 % 에 따라 단계 인디케이터를 active/done으로 바꾼다 */
function _updatePipelineSteps(pct) {
  // 각 단계 완료 기준 %: 음성(20), 배경(40), 자막(88), 조립(100)
  const steps = [
    { el: PSTEPS.voice,    done: 20 },
    { el: PSTEPS.bg,       done: 40 },
    { el: PSTEPS.sub,      done: 88 },
    { el: PSTEPS.assemble, done: 100 },
  ];
  let reachedActive = false;
  for (let i = steps.length - 1; i >= 0; i--) {
    const { el, done } = steps[i];
    if (pct >= done) {
      el.classList.remove('active'); el.classList.add('done');
    } else if (!reachedActive) {
      el.classList.remove('done'); el.classList.add('active');
      reachedActive = true;
    } else {
      el.classList.remove('active', 'done');
    }
  }
}

/* ====================================================
   새 숏츠 만들기 버튼 — 창작 UI 초기화
   ==================================================== */
pipelineNewBtn.addEventListener('click', () => {
  // ── 텍스트 초기화 ──
  topicInput.value             = '';
  scriptTextarea.value         = '';
  pipelineTopic                = '';

  // ── 카드 표시 초기화 ──
  scriptCard.style.display           = 'block';
  pipelineResultCard.style.display   = 'none';
  srtDownloadBtn.style.display       = 'none';
  srtPreview.style.display           = 'none';
  srtContent.textContent             = '';
  approveScriptBtn.disabled          = false;

  // ── 소스 업로드 초기화 ──
  sourceFilename                     = null;
  document.getElementById('source-preview-wrap').style.display = 'none';
  document.getElementById('source-drop-zone').style.display    = 'block';
  document.getElementById('source-upload-progress').style.display = 'none';

  // ── 출처 텍스트 초기화 ──
  const srcTxt = document.getElementById('source-text-input');
  if (srcTxt) srcTxt.value = '출처: 실버크라운';

  // ── 토글 초기화 ──
  document.getElementById('use-tts-toggle').checked      = true;
  document.getElementById('use-subtitle-toggle').checked = true;

  // ── 템플릿 초기화 (냠냠코기) ──
  const nmRadio = document.querySelector('input[name="template"][value="namnam"]');
  if (nmRadio) { nmRadio.checked = true; applyTemplateSwitch('namnam'); }

  // ── 위치 핸들 기본값 초기화 ──
  const posDefaults = {
    banner_h: 240, video_y_namnam: 240, title_y: 320,
    video_y_silver: 580, subtitle_y: 1720, source_y: 1620,
  };
  Object.entries(posDefaults).forEach(([key, v]) => {
    const inp = document.getElementById(POS_INPUT[key]);
    if (inp) inp.value = v;
    const sp  = document.getElementById(POS_YSPAN[key]);
    if (sp)  sp.textContent = v;
  });

  // ── 폰트 크기 기본값 초기화 ──
  const styDefaults = {
    banner_font_size: 60, title_font_size: 65,
    subtitle_font_size: 55, source_font_size: 40,
  };
  Object.entries(styDefaults).forEach(([key, v]) => setStyVal(key, v));

  document.getElementById('topic-card').scrollIntoView({ behavior: 'smooth' });
});

/* 템플릿 라디오 버튼 — 선택된 항목 테두리 강조 */
document.querySelectorAll('input[name="template"]').forEach(radio => {
  radio.addEventListener('change', () => {
    document.querySelectorAll('input[name="template"]').forEach(r => {
      const label = r.closest('label');
      if (r.checked) {
        label.style.borderColor = 'var(--accent)';
        label.style.background  = 'rgba(99,102,241,.08)';
      } else {
        label.style.borderColor = 'var(--border)';
        label.style.background  = '';
      }
    });
  });
});

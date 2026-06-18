/* =====================================================
   main.js — 숏츠 메이커
   ===================================================== */

// ── 전역 상태 ──────────────────────────────────────
let uploadedFilename = null;
let originalBase     = null;
let _uploadInfo      = {};
let videoDim = { w: 0, h: 0 };
let cropPx   = { x: 0, y: 0, w: 0, h: 0 };
let bgMode   = 'none';
let blurLevel   = 20;
let solidColor  = '000000';
let sourceFilename = null;
let sourceDuration = 0;
let customLayers   = [];
let _layerCounter  = 0;
let _pendingStudio = null; // 'crop' | 'layout' | 'subtitle'
let subtitleSegments = [];
const MIN_PX = 20;

// ── DOM 참조 ───────────────────────────────────────
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
const sourcePreviewWrap    = document.getElementById('source-preview-wrap');
const sourcePreviewImg     = document.getElementById('source-preview-img');
const sourceFilenameLabel  = document.getElementById('source-filename-label');
const sourceRefreshBtn     = document.getElementById('source-refresh-btn');
const seekSlider           = document.getElementById('preview-seek-slider');
const seekLabel            = document.getElementById('preview-seek-label');
const topicInput           = document.getElementById('topic-input');
const pipelineProgressCard = document.getElementById('pipeline-progress-card');
const pipelineFill         = document.getElementById('pipeline-fill');
const pipelineText         = document.getElementById('pipeline-text');
const pipelineResultCard   = document.getElementById('pipeline-result-card');
const pipelineDownloadBtn  = document.getElementById('pipeline-download-btn');
const pipelineNewBtn       = document.getElementById('pipeline-new-btn');
const pipelineEta          = document.getElementById('pipeline-eta');
const apiWarning           = document.getElementById('api-warning');
const ttsSpeedSlider       = document.getElementById('tts-speed-slider');
const ttsSpeedLabel        = document.getElementById('tts-speed-label');

/* ====================================================
   섹션 전환 헬퍼
   ==================================================== */
function hideAllSections() {
  document.getElementById('crop-section').style.display     = 'none';
  document.getElementById('layout-section').style.display   = 'none';
  document.getElementById('subtitle-section').style.display = 'none';
  document.getElementById('tts-section').style.display      = 'none';
}

function _showUploadFor(studio) {
  _pendingStudio = studio;
  document.getElementById('mode-select-card').style.display = 'none';
  document.getElementById('upload-card').style.display      = 'block';
  requestAnimationFrame(() =>
    document.getElementById('upload-card').scrollIntoView({ behavior: 'smooth', block: 'start' })
  );
}

function _initLayoutAfterUpload() {
  if (sourceDuration > 0) {
    seekSlider.max   = Math.floor(sourceDuration);
    seekSlider.value = Math.min(3, Math.floor(sourceDuration));
    seekLabel.textContent = parseFloat(seekSlider.value).toFixed(1) + 's';
  }
  sourceFilenameLabel.textContent = originalBase || '';
  document.getElementById('source-preview-loading').style.display = 'block';
  sourcePreviewWrap.style.display = 'none';
  document.getElementById('layout-apply-card').style.display = 'block';
  requestTemplatePreview();
}

/* ====================================================
   모드 버튼
   ==================================================== */
document.getElementById('mode-btn-crop').addEventListener('click', () => {
  hideAllSections();
  document.getElementById('crop-section').style.display = 'block';
  _showUploadFor('crop');
});

document.getElementById('mode-btn-layout').addEventListener('click', () => {
  hideAllSections();
  document.getElementById('layout-apply-card').style.display = 'none';
  document.getElementById('layout-section').style.display = 'block';
  _showUploadFor('layout');
});

document.getElementById('mode-btn-tts').addEventListener('click', () => {
  hideAllSections();
  document.getElementById('mode-select-card').style.display = 'none';
  document.getElementById('tts-section').style.display = 'block';
  requestAnimationFrame(() =>
    document.getElementById('tts-section').scrollIntoView({ behavior: 'smooth', block: 'start' })
  );
});

document.getElementById('mode-btn-subtitle').addEventListener('click', () => {
  hideAllSections();
  document.getElementById('subtitle-section').style.display = 'block';
  _showUploadFor('subtitle');
});

/* ====================================================
   업로드 — XHR
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

  document.getElementById('mode-select-card').style.display = 'none';
  hideAllSections();
  previewWrap.style.display = 'none';
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
    _uploadInfo      = data.info || {};
    sourceFilename   = data.filename;
    sourceDuration   = _uploadInfo.duration || 0;

    dropZone.innerHTML = `
      <strong>✅ ${file.name}</strong>
      <p style="color:var(--success)">업로드 완료 · 다시 클릭하면 교체</p>
    `;

    const info = _uploadInfo;
    if (info.width) {
      document.getElementById('video-info').style.display = 'flex';
      document.getElementById('video-info').innerHTML =
        `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`;
    }

    document.getElementById('upload-card').style.display = 'none';
    showToast('업로드 완료!', 'success');

    if (_pendingStudio === 'crop') {
      requestAnimationFrame(() => initCropUI(uploadedFilename, _uploadInfo));
    } else if (_pendingStudio === 'layout') {
      _initLayoutAfterUpload();
      requestAnimationFrame(() =>
        document.getElementById('layout-section').scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
    } else if (_pendingStudio === 'subtitle') {
      document.getElementById('subtitle-section').style.display = 'block';
      requestAnimationFrame(() =>
        document.getElementById('subtitle-section').scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
    }
  };

  xhr.onerror = () => { uploadProgressWrap.style.display = 'none'; showToast('네트워크 오류', 'error'); resetDrop(); };
  xhr.send(form);
}

/* ====================================================
   크롭 UI
   ==================================================== */
function initCropUI(filename, info) {
  editCard.style.display    = 'none';
  actionCard.style.display  = 'none';
  previewWrap.style.display = 'none';
  cropPx = { x: 0, y: 0, w: 0, h: 0 };

  videoDim = { w: info.width || 1280, h: info.height || 720 };

  previewVideo.removeAttribute('src');
  previewVideo.load();

  function onMetadataLoaded() {
    editCard.style.display   = 'block';
    actionCard.style.display = 'flex';
    previewWrap.style.display = 'none';

    const ratio = videoDim.w / videoDim.h;
    ratioBadge.style.display = Math.abs(ratio - 9 / 16) < 0.01 ? 'block' : 'none';
    previewVideo.currentTime = Math.min(previewVideo.duration * 0.05, 3);

    requestAnimationFrame(() => {
      initCropBox();
      requestAnimationFrame(() => {
        document.getElementById('crop-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  previewVideo.addEventListener('loadedmetadata', onMetadataLoaded, { once: true });
  previewVideo.src = `/uploads/${encodeURIComponent(filename)}`;
  previewVideo.load();
}

function initCropBox() {
  const vw = videoDim.w, vh = videoDim.h;
  const ratio  = vw / vh;
  const target = 9 / 16;
  let cw, ch;
  if (ratio > target + 0.01) {
    ch = vh; cw = Math.round(ch * target); lock916.checked = true;
  } else {
    cw = vw; ch = Math.round(cw / target); lock916.checked = false;
  }
  cw -= cw % 2; ch -= ch % 2;
  cropPx = { x: Math.round((vw - cw) / 2), y: Math.round((vh - ch) / 2), w: cw, h: ch };
  renderCropBox();
}

function renderCropBox() {
  const displayW = cropContainer.offsetWidth;
  const displayH = displayW / videoDim.w * videoDim.h;
  const scaleX   = displayW / videoDim.w;
  const scaleY   = displayH / videoDim.h;
  cropBox.style.left   = (cropPx.x * scaleX) + 'px';
  cropBox.style.top    = (cropPx.y * scaleY) + 'px';
  cropBox.style.width  = (cropPx.w * scaleX) + 'px';
  cropBox.style.height = (cropPx.h * scaleY) + 'px';
  const w = Math.round(cropPx.w), h = Math.round(cropPx.h);
  cropDims.textContent = `결과: ${w} × ${h} px  (${(w / h).toFixed(2)} : 1)`;
}

window.addEventListener('resize', () => { if (uploadedFilename) renderCropBox(); });

/* ====================================================
   크롭 박스 드래그
   ==================================================== */
let drag = null;

cropBox.querySelectorAll('.handle').forEach(handle => {
  handle.addEventListener('mousedown',  e => startDrag(e, handle.dataset.dir));
  handle.addEventListener('touchstart', e => startDrag(e, handle.dataset.dir), { passive: false });
});
cropBox.addEventListener('mousedown',  e => { if (e.target === cropBox) startDrag(e, 'move'); });
cropBox.addEventListener('touchstart', e => { if (e.target === cropBox) startDrag(e, 'move'); }, { passive: false });

function startDrag(e, dir) {
  e.preventDefault(); e.stopPropagation();
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
  const sc  = drag.startCrop;
  const lock = lock916.checked;
  let { x, y, w, h } = sc;

  switch (drag.dir) {
    case 'move': x = clamp(sc.x + dvx, 0, videoDim.w - sc.w); y = clamp(sc.y + dvy, 0, videoDim.h - sc.h); break;
    case 'n': { const ny = clamp(sc.y + dvy, 0, sc.y + sc.h - MIN_PX); h = sc.h - (ny - sc.y); y = ny; if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w-w)/2, 0, videoDim.w-w); } break; }
    case 's': { h = clamp(sc.h + dvy, MIN_PX, videoDim.h - sc.y); if (lock) { w = h * (9/16); x = clamp(sc.x + (sc.w-w)/2, 0, videoDim.w-w); } break; }
    case 'e': { w = clamp(sc.w + dvx, MIN_PX, videoDim.w - sc.x); if (lock) { h = w * (16/9); y = clamp(sc.y + (sc.h-h)/2, 0, videoDim.h-h); } break; }
    case 'w': { const nx = clamp(sc.x + dvx, 0, sc.x + sc.w - MIN_PX); w = sc.w-(nx-sc.x); x = nx; if (lock) { h = w*(16/9); y = clamp(sc.y+(sc.h-h)/2,0,videoDim.h-h); } break; }
    case 'nw': { const nx=clamp(sc.x+dvx,0,sc.x+sc.w-MIN_PX),ny=clamp(sc.y+dvy,0,sc.y+sc.h-MIN_PX); w=sc.w-(nx-sc.x); h=sc.h-(ny-sc.y); x=nx; y=ny; if(lock){h=w*(16/9);y=sc.y+sc.h-h;} break; }
    case 'ne': { w=clamp(sc.w+dvx,MIN_PX,videoDim.w-sc.x); const ny2=clamp(sc.y+dvy,0,sc.y+sc.h-MIN_PX); h=sc.h-(ny2-sc.y); y=ny2; if(lock){h=w*(16/9);y=sc.y+sc.h-h;} break; }
    case 'sw': { const nx2=clamp(sc.x+dvx,0,sc.x+sc.w-MIN_PX); w=sc.w-(nx2-sc.x); x=nx2; h=clamp(sc.h+dvy,MIN_PX,videoDim.h-sc.y); if(lock){h=w*(16/9);} break; }
    case 'se': { w=clamp(sc.w+dvx,MIN_PX,videoDim.w-sc.x); h=clamp(sc.h+dvy,MIN_PX,videoDim.h-sc.y); if(lock){h=w*(16/9);} break; }
  }

  w = clamp(w, MIN_PX, videoDim.w); h = clamp(h, MIN_PX, videoDim.h);
  x = clamp(x, 0, videoDim.w - w); y = clamp(y, 0, videoDim.h - h);
  cropPx = { x, y, w, h };
  renderCropBox();
}

resetBtn.addEventListener('click', initCropBox);

lock916.addEventListener('change', () => {
  if (!lock916.checked) return;
  let w = cropPx.w, h = Math.round(w * 16 / 9);
  if (h > videoDim.h) { h = videoDim.h; w = Math.round(h * 9 / 16); }
  w -= w % 2; h -= h % 2;
  cropPx = { x: cropPx.x, y: Math.min(cropPx.y, videoDim.h - h), w, h };
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
  const labels = { none: '✂️ 크롭 적용', blur: '🌫 블러 배경 적용', solid: '🎨 단색 배경 적용' };
  processBtn.textContent = labels[bgMode];
}

blurSlider.addEventListener('input', () => { blurLevel = parseInt(blurSlider.value, 10); blurValueEl.textContent = blurLevel; });
blurPreviewBtn.addEventListener('click', () => requestPreview());

const COLOR_NAMES = {
  '000000': '검정', 'ffffff': '흰색', '1a1a2e': '딥 블루',
  '2d1b69': '퍼플', '0f3460': '다크 블루', '16213e': '네이비',
};

function selectColor(hex) {
  solidColor = hex.replace('#', '').toLowerCase();
  solidColorPicker.value = '#' + solidColor;
  solidColorLabel.textContent = `선택: ${COLOR_NAMES[solidColor] || '사용자 지정'} (#${solidColor})`;
  document.querySelectorAll('.color-preset').forEach(b => { b.classList.toggle('active', b.dataset.color === solidColor); });
}

document.querySelectorAll('.color-preset').forEach(btn => { btn.addEventListener('click', () => selectColor(btn.dataset.color)); });
solidColorPicker.addEventListener('input', () => selectColor(solidColorPicker.value));
solidPreviewBtn.addEventListener('click', () => requestPreview());

/* ====================================================
   서버 프리뷰 (크롭 스튜디오)
   ==================================================== */
function fmtTime(sec) {
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

async function requestPreview() {
  if (!uploadedFilename) { showToast('먼저 영상을 올려주세요.', 'error'); return; }
  const btn = bgMode === 'blur' ? blurPreviewBtn : solidPreviewBtn;
  const origText = btn.textContent;
  btn.disabled = true; btn.textContent = '⏳ 생성 중...';
  const dur = previewVideo.duration || 10;
  const seekTimes = [dur * 0.2, dur * 0.5, dur * 0.8];
  const makeBody = (seekTime) => {
    const body = { filename: uploadedFilename, bg_mode: bgMode, seek_time: seekTime,
      crop: { x: Math.round(cropPx.x), y: Math.round(cropPx.y), w: Math.round(cropPx.w), h: Math.round(cropPx.h) } };
    if (bgMode === 'blur') body.blur = blurLevel; else body.color = solidColor;
    return body;
  };
  try {
    const results = await Promise.all(seekTimes.map(t =>
      fetch('/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(makeBody(t)) })
    ));
    for (const res of results) { if (!res.ok) { const j = await res.json().catch(() => ({})); showToast(j.error || '프리뷰 생성 실패', 'error'); return; } }
    const blobs = await Promise.all(results.map(r => r.blob()));
    blobs.forEach((blob, i) => {
      if (previewImgs[i].src?.startsWith('blob:')) URL.revokeObjectURL(previewImgs[i].src);
      previewImgs[i].src = URL.createObjectURL(blob);
      previewLabels[i].textContent = fmtTime(seekTimes[i]);
    });
    previewWrap.style.display = 'block';
  } catch { showToast('프리뷰 오류', 'error'); }
  finally { btn.disabled = false; btn.textContent = origText; }
}

/* ====================================================
   크롭 처리
   ==================================================== */
processBtn.addEventListener('click', async () => {
  if (!uploadedFilename) return;
  if (cropPx.w <= 0 || cropPx.h <= 0) { showToast('크롭 영역이 설정되지 않았습니다.', 'error'); return; }
  processBtn.disabled = true;
  resultSec.style.display = 'none';
  showProgress('처리 시작 중...', 0);
  const body = {
    filename: uploadedFilename, original_base: originalBase, bg_mode: bgMode,
    crop: { x: Math.round(cropPx.x), y: Math.round(cropPx.y), w: Math.round(cropPx.w), h: Math.round(cropPx.h) },
  };
  if (bgMode === 'blur')  body.blur  = blurLevel;
  if (bgMode === 'solid') body.color = solidColor;
  try {
    const res  = await fetch('/process', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json();
    if (!data.ok) { showToast(data.error || '처리 실패', 'error'); hideProgress(); processBtn.disabled = false; return; }
    subscribeProgress(data.job_id, payload => {
      if (payload.error) { showToast(payload.error, 'error'); hideProgress(); processBtn.disabled = false; return; }
      updateProgress(payload.pct, payload.msg || '처리 중...');
      if (payload.done) {
        hideProgress();
        const dlBtn = document.getElementById('download-btn');
        dlBtn.href = `/download/${encodeURIComponent(payload.result)}`; dlBtn.download = payload.result;
        resultSec.style.display = 'block'; processBtn.disabled = false;
        showToast('완성! 다운로드 버튼을 눌러주세요.', 'success');
      }
    });
  } catch { hideProgress(); processBtn.disabled = false; showToast('오류가 발생했습니다.', 'error'); }
});


/* ====================================================
   YouTube 가져오기
   ==================================================== */
ytBtn.addEventListener('click', fetchYoutube);
ytUrl.addEventListener('keydown', e => { if (e.key === 'Enter') fetchYoutube(); });

async function fetchYoutube() {
  const url = ytUrl.value.trim();
  if (!url) return;
  ytBtn.disabled = true; ytBtn.textContent = '⏳ 다운로드 중...';
  document.getElementById('mode-select-card').style.display = 'none';
  hideAllSections();
  previewWrap.style.display = 'none';
  cropPx = { x: 0, y: 0, w: 0, h: 0 };
  dropZone.innerHTML = `<strong>YouTube 영상 다운로드 중...</strong><p>${url}</p>`;
  try {
    const res  = await fetch('/fetch-youtube', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) });
    const data = await res.json();
    if (!data.ok) { showToast(data.error || '다운로드 실패', 'error'); resetDrop(); return; }
    uploadedFilename = data.filename; originalBase = data.original_base || 'video';
    _uploadInfo = data.info || {}; sourceFilename = data.filename; sourceDuration = _uploadInfo.duration || 0;
    const info = _uploadInfo;
    if (info.width) { document.getElementById('video-info').style.display = 'flex'; document.getElementById('video-info').innerHTML = `해상도 <span>${info.width}×${info.height}</span> &nbsp; 길이 <span>${info.duration_str}</span>`; }
    dropZone.innerHTML = `<strong>✅ ${data.original_base}</strong><p style="color:var(--success)">${info.duration_str ? info.duration_str + ' · ' : ''}${info.width ? info.width + '×' + info.height : ''}</p>`;
    document.getElementById('upload-card').style.display = 'none';
    showToast('YouTube 영상 준비 완료!', 'success'); ytUrl.value = '';

    if (_pendingStudio === 'crop') {
      requestAnimationFrame(() => initCropUI(uploadedFilename, _uploadInfo));
    } else if (_pendingStudio === 'layout') {
      _initLayoutAfterUpload();
      requestAnimationFrame(() =>
        document.getElementById('layout-section').scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
    } else if (_pendingStudio === 'subtitle') {
      document.getElementById('subtitle-section').style.display = 'block';
      requestAnimationFrame(() =>
        document.getElementById('subtitle-section').scrollIntoView({ behavior: 'smooth', block: 'start' })
      );
    }
  } catch { showToast('네트워크 오류', 'error'); resetDrop(); }
  finally { ytBtn.disabled = false; ytBtn.textContent = '▶ 가져오기'; }
}

/* ====================================================
   SSE 구독
   ==================================================== */
function subscribeProgress(jobId, onData) {
  const es = new EventSource(`/progress/${jobId}`);
  es.onmessage = e => {
    let payload; try { payload = JSON.parse(e.data); } catch { return; }
    onData(payload);
    if (payload.done || payload.error) es.close();
  };
  es.onerror = () => { es.close(); onData({ done: true, error: '연결 오류가 발생했습니다.' }); };
}

/* ====================================================
   진행 바 (크롭 스튜디오)
   ==================================================== */
function showProgress(msg, pct) {
  progressSec.style.display = 'block';
  progressText.textContent  = msg || '처리 중...';
  if (!pct) { progressFill.classList.add('indeterminate'); progressFill.style.width = ''; }
  else { progressFill.classList.remove('indeterminate'); progressFill.style.width = pct + '%'; }
}
function updateProgress(pct, msg) {
  if (pct > 0) { progressFill.classList.remove('indeterminate'); progressFill.style.width = pct + '%'; }
  if (msg) progressText.textContent = msg;
}
function hideProgress() {
  progressSec.style.display = 'none'; progressFill.classList.remove('indeterminate'); progressFill.style.width = '0%';
}

/* ====================================================
   레이아웃/TTS — 미리보기 슬라이더
   ==================================================== */
seekSlider.addEventListener('input', () => {
  seekLabel.textContent = parseFloat(seekSlider.value).toFixed(1) + 's';
  debouncedPreview();
});

/* ====================================================
   커스텀 텍스트 레이어
   ==================================================== */
document.getElementById('add-text-layer-btn').addEventListener('click', () => addCustomLayer());

function addCustomLayer(init = {}) {
  const id             = 'cl-' + (++_layerCounter);
  const y              = init.y               ?? 960;
  const fontSize       = init.font_size       ?? 50;
  const text           = init.text            || '';
  const highlightColor = init.highlight_color || '#ffcc00';
  const baseColor      = init.base_color      || '#ffffff';

  customLayers.push({ id, text, y, font_size: fontSize, highlight_color: highlightColor, base_color: baseColor });

  const container = document.getElementById('custom-layers-container');
  const card      = document.createElement('div');
  card.id         = 'layer-card-' + id;
  card.style.cssText = 'background:var(--surface-2,#222);border:1px solid var(--border,#333);border-radius:8px;padding:10px;display:flex;flex-direction:column;gap:8px;';
  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:6px">
      <input type="text" placeholder="텍스트 입력" value="${text.replace(/"/g,'&quot;')}"
             style="flex:1;background:var(--surface,#1a1a1a);border:1px solid var(--border,#333);border-radius:6px;padding:6px 8px;color:#fff;font-size:.9rem"
             class="layer-text-input">
      <label title="강조색 (첫 단어)" style="cursor:pointer;display:flex;align-items:center">
        <input type="color" class="layer-highlight-color" value="${highlightColor}"
               style="width:26px;height:26px;border:2px solid var(--border,#333);border-radius:5px;padding:1px;cursor:pointer;background:none">
      </label>
      <label title="기본색" style="cursor:pointer;display:flex;align-items:center">
        <input type="color" class="layer-base-color" value="${baseColor}"
               style="width:26px;height:26px;border:2px solid var(--border,#333);border-radius:5px;padding:1px;cursor:pointer;background:none">
      </label>
      <button class="layer-del-btn"
              style="background:#c0392b;color:#fff;border:none;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:.85rem">✕</button>
    </div>
    <div style="display:flex;align-items:center;gap:8px">
      <span style="font-size:.75rem;color:var(--text-muted,#888);white-space:nowrap">크기</span>
      <button data-delta="-2" class="layer-sz-btn"
              style="background:none;border:1px solid var(--border,#333);border-radius:4px;padding:2px 8px;color:#fff;cursor:pointer">−</button>
      <span class="layer-sz-num" style="font-size:.85rem;min-width:28px;text-align:center">${fontSize}pt</span>
      <button data-delta="2" class="layer-sz-btn"
              style="background:none;border:1px solid var(--border,#333);border-radius:4px;padding:2px 8px;color:#fff;cursor:pointer">+</button>
      <span style="font-size:.75rem;color:var(--text-muted,#888);margin-left:auto">드래그로 위치 조정</span>
    </div>`;
  container.appendChild(card);

  card.querySelector('.layer-text-input').addEventListener('input', e => {
    setLayerProp(id, 'text', e.target.value);
    const h = document.getElementById('layer-handle-' + id);
    if (h) h.querySelector('.layer-handle-label').textContent = e.target.value || '텍스트';
    debouncedPreview();
  });
  card.querySelectorAll('.layer-sz-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const next = Math.max(12, Math.min(120, (getLayerProp(id, 'font_size') || 50) + parseInt(btn.dataset.delta)));
      setLayerProp(id, 'font_size', next);
      card.querySelector('.layer-sz-num').textContent = next + 'pt';
      debouncedPreview();
    });
  });
  card.querySelector('.layer-highlight-color').addEventListener('input', e => {
    setLayerProp(id, 'highlight_color', e.target.value);
    const h = document.getElementById('layer-handle-' + id);
    if (h) { h.style.borderColor = e.target.value; h.querySelector('.layer-handle-label').style.color = e.target.value; }
    debouncedPreview();
  });
  card.querySelector('.layer-base-color').addEventListener('input', e => {
    setLayerProp(id, 'base_color', e.target.value);
    debouncedPreview();
  });
  card.querySelector('.layer-del-btn').addEventListener('click', () => removeCustomLayer(id));

  const wrap   = document.getElementById('preview-drag-wrap');
  const handle = document.createElement('div');
  handle.id        = 'layer-handle-' + id;
  handle.className = 'drag-handle layer-drag-handle';
  handle.style.cssText = `top:${(y / 1920 * 100).toFixed(2)}%;border-color:${highlightColor};`;
  handle.innerHTML = `<span class="layer-handle-label" style="color:${highlightColor}">${text || '텍스트'}</span>`;
  wrap.appendChild(handle);

  handle.addEventListener('mousedown', e => {
    e.preventDefault();
    _drag = { handle, layerId: id, rect: wrap.getBoundingClientRect(), startY: e.clientY, startV: getLayerProp(id, 'y') ?? 960 };
  });
  handle.addEventListener('touchstart', e => {
    e.preventDefault();
    _drag = { handle, layerId: id, rect: wrap.getBoundingClientRect(), startY: e.touches[0].clientY, startV: getLayerProp(id, 'y') ?? 960 };
  }, { passive: false });

  debouncedPreview();
}

function removeCustomLayer(id) {
  customLayers = customLayers.filter(l => l.id !== id);
  document.getElementById('layer-card-'   + id)?.remove();
  document.getElementById('layer-handle-' + id)?.remove();
  debouncedPreview();
}

function getLayerProp(id, k) { return (customLayers.find(l => l.id === id) || {})[k]; }
function setLayerProp(id, k, v) { const layer = customLayers.find(l => l.id === id); if (layer) layer[k] = v; }

/* ====================================================
   레이아웃 위치 + 폰트 크기
   ==================================================== */
const POS_INPUT = {
  banner_h: 'pos-banner-h', video_y_namnam: 'pos-video-y-namnam',
  title_y: 'pos-title-y', video_y_silver: 'pos-video-y-silver', subtitle_y: 'pos-subtitle-y',
};
const POS_YSPAN = {
  banner_h: 'dhv-banner-h', video_y_namnam: 'dhv-video-y-nm',
  title_y: 'dhv-title-y', video_y_silver: 'dhv-video-y-sc', subtitle_y: 'dhv-subtitle-y',
};
const STY_INPUT = { banner_font_size: 'sty-banner-size', title_font_size: 'sty-title-size', subtitle_font_size: 'sty-subtitle-size' };
const STY_SPAN  = { banner_font_size: 'szn-banner', title_font_size: 'szn-title', subtitle_font_size: 'szn-subtitle' };

function posVal(key) { return parseInt(document.getElementById(POS_INPUT[key])?.value) || 0; }
function setPosVal(key, v) {
  const handle = document.querySelector(`.drag-handle[data-key="${key}"]`);
  const min = parseInt(handle?.dataset.min) || 0;
  const max = parseInt(handle?.dataset.max) || 1920;
  v = Math.round(Math.max(min, Math.min(max, v)) / 10) * 10;
  const inp = document.getElementById(POS_INPUT[key]); if (inp) inp.value = v;
  const sp  = document.getElementById(POS_YSPAN[key]); if (sp)  sp.textContent = v;
  return v;
}
function styVal(key) { return parseInt(document.getElementById(STY_INPUT[key])?.value) || 0; }
function setStyVal(key, v) {
  v = Math.max(12, Math.min(120, v));
  const inp = document.getElementById(STY_INPUT[key]); if (inp) inp.value = v;
  const sp  = document.getElementById(STY_SPAN[key]);  if (sp)  sp.textContent = v;
  return v;
}

function syncHandlePositions() {
  document.querySelectorAll('.drag-handle:not(.layer-drag-handle)').forEach(h => {
    const v = posVal(h.dataset.key);
    h.style.top = (v / 1920 * 100) + '%';
  });
}

// ── 드래그 ──────────────────────────────────────────
let _drag = null;

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.drag-handle').forEach(handle => {
    const onStart = (e) => {
      if (!handle.dataset.key) return;
      if (e.target.classList.contains('sz-btn')) return;
      e.preventDefault();
      const wrap = document.getElementById('preview-drag-wrap');
      _drag = { handle, key: handle.dataset.key, rect: wrap.getBoundingClientRect(),
        startY: e.touches ? e.touches[0].clientY : e.clientY, startV: posVal(handle.dataset.key) };
    };
    handle.addEventListener('mousedown',  onStart);
    handle.addEventListener('touchstart', onStart, { passive: false });
  });

  document.querySelectorAll('.sz-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      setStyVal(btn.dataset.sty, styVal(btn.dataset.sty) + parseInt(btn.dataset.delta));
      if (sourceFilename) debouncedPreview();
    });
  });
});

document.addEventListener('mousemove', (e) => {
  if (!_drag) return;
  const dy = e.clientY - _drag.startY;
  const dv = (dy / _drag.rect.height) * 1920;
  if (_drag.layerId) {
    const v = Math.round(Math.max(0, Math.min(1900, _drag.startV + dv)) / 10) * 10;
    setLayerProp(_drag.layerId, 'y', v);
    _drag.handle.style.top = (v / 1920 * 100) + '%';
  } else {
    const v = setPosVal(_drag.key, _drag.startV + dv);
    _drag.handle.style.top = (v / 1920 * 100) + '%';
  }
});
document.addEventListener('touchmove', (e) => {
  if (!_drag) return;
  e.preventDefault();
  const dy = e.touches[0].clientY - _drag.startY;
  const dv = (dy / _drag.rect.height) * 1920;
  if (_drag.layerId) {
    const v = Math.round(Math.max(0, Math.min(1900, _drag.startV + dv)) / 10) * 10;
    setLayerProp(_drag.layerId, 'y', v);
    _drag.handle.style.top = (v / 1920 * 100) + '%';
  } else {
    const v = setPosVal(_drag.key, _drag.startV + dv);
    _drag.handle.style.top = (v / 1920 * 100) + '%';
  }
}, { passive: false });

document.addEventListener('mouseup',  () => { if (_drag) { _drag = null; debouncedPreview(); } });
document.addEventListener('touchend', () => { if (_drag) { _drag = null; debouncedPreview(); } });

function getPositions() {
  const tpl = document.querySelector('input[name="template"]:checked')?.value || 'namnam';
  const sub_margin = 1920 - posVal('subtitle_y');
  if (tpl === 'silver_crown') {
    return { title_y: posVal('title_y'), video_y: posVal('video_y_silver'), subtitle_margin_v: sub_margin };
  } else {
    return { banner_h: posVal('banner_h'), video_y: posVal('video_y_namnam'), subtitle_margin_v: sub_margin };
  }
}

function getStyles() {
  return { banner_font_size: styVal('banner_font_size'), title_font_size: styVal('title_font_size'), subtitle_font_size: styVal('subtitle_font_size') };
}

// ── 템플릿 전환 ──────────────────────────────────────
function applyTemplateSwitch(tpl) {
  const isSilver = tpl === 'silver_crown';
  document.querySelectorAll('.drag-handle:not(.layer-drag-handle)').forEach(h => {
    const forNm = h.dataset.nm === '1';
    const forSc = h.dataset.sc === '1';
    h.style.display = (forNm && !isSilver) || (forSc && isSilver) || (forNm && forSc) ? '' : 'none';
  });
  document.getElementById('tpl-namnam').style.borderColor = isSilver ? 'var(--border)' : 'var(--accent)';
  document.getElementById('tpl-silver').style.borderColor = isSilver ? 'var(--accent)' : 'var(--border)';
}

document.querySelectorAll('input[name="template"]').forEach(radio => {
  radio.addEventListener('change', () => {
    applyTemplateSwitch(radio.value);
    if (sourceFilename) requestTemplatePreview();
  });
});

/* 템플릿 라디오 강조 */
document.querySelectorAll('input[name="template"]').forEach(radio => {
  radio.addEventListener('change', () => {
    document.querySelectorAll('input[name="template"]').forEach(r => {
      const label = r.closest('label');
      if (r.checked) { label.style.borderColor = 'var(--accent)'; label.style.background = 'rgba(99,102,241,.08)'; }
      else           { label.style.borderColor = 'var(--border)'; label.style.background = ''; }
    });
  });
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
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filename: sourceFilename, template: tpl, title,
        positions: getPositions(), styles: getStyles(),
        seek_time: Math.min(parseFloat(seekSlider?.value || 3), sourceDuration || 30),
        custom_layers: customLayers,
      }),
    });
    const data = await res.json();
    const loadingEl = document.getElementById('source-preview-loading');
    if (data.ok) {
      sourcePreviewImg.src = data.preview_url + '?t=' + Date.now();
      sourcePreviewImg.onload = () => {
        if (loadingEl) loadingEl.style.display = 'none';
        sourcePreviewWrap.style.display = 'block';
        syncHandlePositions();
      };
    } else {
      if (loadingEl) loadingEl.style.display = 'none';
      showToast('미리보기 실패: ' + data.error, 'error');
    }
  } catch (e) {
    const loadingEl = document.getElementById('source-preview-loading');
    if (loadingEl) loadingEl.style.display = 'none';
    showToast('미리보기 오류: ' + e.message, 'error');
  }
}

topicInput.addEventListener('input', () => { if (sourceFilename) debouncedPreview(); });
sourceRefreshBtn.addEventListener('click', requestTemplatePreview);

ttsSpeedSlider.addEventListener('input', () => {
  const v = parseFloat(ttsSpeedSlider.value || '1.0').toFixed(2).replace(/0+$/, '').replace(/\.$/, '');
  ttsSpeedLabel.textContent = v + 'x';
});

/* ====================================================
   레이아웃 파이프라인 실행
   ==================================================== */
let pipelineTopic = '';

async function runPipeline() {
  if (!sourceFilename) { showToast('영상을 먼저 업로드해주세요.', 'error'); return; }

  pipelineTopic = topicInput.value.trim() || '숏츠';
  document.getElementById('layout-apply-btn').disabled = true;
  document.getElementById('layout-apply-card').style.display = 'none';
  pipelineProgressCard.style.display = 'block';
  pipelineResultCard.style.display   = 'none';
  pipelineFill.style.width = '0%';
  pipelineText.textContent = '준비 중...';

  const _start = Date.now();
  let _etaTimer = setInterval(() => {
    const sec = Math.floor((Date.now() - _start) / 1000);
    const m = Math.floor(sec / 60), s = sec % 60;
    pipelineEta.textContent = m > 0 ? `진행 중: ${m}분 ${s}초 경과` : `진행 중: ${s}초 경과`;
  }, 1000);
  pipelineEta.style.display = 'block';

  try {
    const res = await fetch('/pipeline/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script: '', topic: pipelineTopic,
        template:        document.querySelector('input[name="template"]:checked')?.value || 'namnam',
        source_filename: sourceFilename,
        use_tts:         false,
        use_subtitle:    false,
        positions:       getPositions(),
        styles:          getStyles(),
        custom_layers:   customLayers,
      }),
    });
    const data = await res.json();

    if (!data.ok) {
      clearInterval(_etaTimer); pipelineEta.style.display = 'none';
      showToast(data.error || '실행 실패', 'error');
      pipelineProgressCard.style.display = 'none';
      document.getElementById('layout-apply-btn').disabled = false;
      document.getElementById('layout-apply-card').style.display = '';
      return;
    }

    subscribeProgress(data.job_id, payload => {
      if (payload.error) {
        clearInterval(_etaTimer); pipelineEta.style.display = 'none';
        pipelineText.textContent = '❌ ' + payload.error;
        pipelineProgressCard.style.display = 'none';
        document.getElementById('layout-apply-btn').disabled = false;
        document.getElementById('layout-apply-card').style.display = '';
        showToast('오류 발생', 'error');
        return;
      }
      pipelineFill.style.width = (payload.pct || 0) + '%';
      if (payload.msg) pipelineText.textContent = payload.msg;

      if (payload.done) {
        clearInterval(_etaTimer);
        pipelineEta.style.display          = 'none';
        pipelineProgressCard.style.display = 'none';
        pipelineResultCard.style.display   = 'block';
        pipelineDownloadBtn.href     = `/download/${payload.result}`;
        pipelineDownloadBtn.download = payload.result;
        const rv = document.getElementById('pipeline-result-video');
        rv.src = `/download/${payload.result}`; rv.style.display = 'block';
        showToast('완성!', 'success');
      }
    });

  } catch {
    clearInterval(_etaTimer); pipelineEta.style.display = 'none';
    showToast('네트워크 오류', 'error');
    pipelineProgressCard.style.display = 'none';
    document.getElementById('layout-apply-btn').disabled = false;
    document.getElementById('layout-apply-card').style.display = '';
  }
}

document.getElementById('layout-apply-btn').addEventListener('click', runPipeline);

/* ====================================================
   TTS 음성 생성
   ==================================================== */
document.getElementById('tts-generate-btn').addEventListener('click', async () => {
  const text  = document.getElementById('tts-textarea').value.trim();
  if (!text) { showToast('텍스트를 입력해주세요.', 'error'); return; }

  const btn = document.getElementById('tts-generate-btn');
  btn.disabled = true; btn.textContent = '⏳ 생성 중...';
  document.getElementById('tts-result-card').style.display = 'none';

  try {
    const res  = await fetch('/tts/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice: document.querySelector('input[name="tts-voice"]:checked')?.value || 'ko-KR-Neural2-C',
        speed: parseFloat(ttsSpeedSlider.value || '1.0'),
      }),
    });
    const data = await res.json();
    if (!data.ok) { showToast(data.error || '생성 실패', 'error'); return; }

    const audio = document.getElementById('tts-result-audio');
    const dlBtn = document.getElementById('tts-download-btn');
    audio.src = data.audio_url;
    dlBtn.href = data.audio_url;
    dlBtn.download = data.filename;
    document.getElementById('tts-result-card').style.display = 'block';
    audio.play();
    showToast('음성 생성 완료!', 'success');
  } catch {
    showToast('네트워크 오류', 'error');
  } finally {
    btn.disabled = false; btn.textContent = '🔊 음성 생성';
  }
});

/* ====================================================
   레이아웃 완성 후 스튜디오 선택으로
   ==================================================== */
pipelineNewBtn.addEventListener('click', () => {
  pipelineResultCard.style.display = 'none';
  document.getElementById('layout-apply-card').style.display = 'none';
  sourcePreviewWrap.style.display = 'none';
  document.getElementById('source-preview-loading').style.display = 'none';
  topicInput.value = ''; pipelineTopic = '';
  seekSlider.value = 3; seekSlider.max = 30; seekLabel.textContent = '3.0s';
  customLayers = []; document.getElementById('custom-layers-container').innerHTML = '';
  const nmRadio = document.querySelector('input[name="template"][value="namnam"]');
  if (nmRadio) { nmRadio.checked = true; applyTemplateSwitch('namnam'); }
  const posDefaults = { banner_h: 240, video_y_namnam: 240, title_y: 320, video_y_silver: 580, subtitle_y: 1720 };
  Object.entries(posDefaults).forEach(([key, v]) => {
    const inp = document.getElementById(POS_INPUT[key]); if (inp) inp.value = v;
    const sp  = document.getElementById(POS_YSPAN[key]); if (sp)  sp.textContent = v;
  });
  Object.entries({ banner_font_size: 60, title_font_size: 65, subtitle_font_size: 55 }).forEach(([key, v]) => setStyVal(key, v));
  goToStudioSelect();
});


/* ====================================================
   파이프라인 설정 상태 확인
   ==================================================== */
async function checkPipelineConfig() {
  try {
    const res  = await fetch('/pipeline/check-config');
    const data = await res.json();
    apiWarning.style.display = data.ok ? 'none' : '';
  } catch { /* 무시 */ }
}
checkPipelineConfig();

/* ====================================================
   뒤로 / 처음으로 버튼
   ==================================================== */
function goToStudioSelect() {
  hideAllSections();
  document.getElementById('upload-card').style.display = 'none';
  // 업로드 상태 초기화
  uploadedFilename = null; originalBase = null; _uploadInfo = {};
  sourceFilename = null; sourceDuration = 0; _pendingStudio = null;
  resetDrop();
  document.getElementById('video-info').style.display = 'none';
  document.getElementById('video-info').innerHTML = '';
  document.getElementById('mode-select-card').style.display = 'block';
  document.getElementById('mode-select-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

document.getElementById('layout-back-btn').addEventListener('click', goToStudioSelect);
document.getElementById('crop-back-btn').addEventListener('click', goToStudioSelect);
document.getElementById('subtitle-back-btn').addEventListener('click', goToStudioSelect);
document.getElementById('tts-back-btn').addEventListener('click', goToStudioSelect);
document.getElementById('crop-restart-btn').addEventListener('click', goToStudioSelect);

/* ====================================================
   자막 스튜디오
   ==================================================== */
document.getElementById('subtitle-analyze-btn').addEventListener('click', async () => {
  if (!uploadedFilename) { showToast('먼저 영상을 업로드해주세요.', 'error'); return; }

  const analyzeBtn = document.getElementById('subtitle-analyze-btn');
  analyzeBtn.disabled = true;
  document.getElementById('subtitle-progress-card').style.display = 'block';
  document.getElementById('subtitle-editor-card').style.display   = 'none';

  const fill    = document.getElementById('subtitle-progress-fill');
  const txtEl   = document.getElementById('subtitle-progress-text');
  fill.classList.add('indeterminate');
  fill.style.width = '';

  try {
    const res  = await fetch('/subtitle/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename: uploadedFilename, original_base: originalBase }),
    });
    const data = await res.json();
    if (!data.ok) {
      showToast(data.error || '분석 실패', 'error');
      document.getElementById('subtitle-progress-card').style.display = 'none';
      analyzeBtn.disabled = false; return;
    }

    subscribeProgress(data.job_id, payload => {
      if (payload.error) {
        showToast(payload.error, 'error');
        document.getElementById('subtitle-progress-card').style.display = 'none';
        analyzeBtn.disabled = false; return;
      }
      if (payload.msg) txtEl.textContent = payload.msg;
      if (payload.pct > 0) { fill.classList.remove('indeterminate'); fill.style.width = payload.pct + '%'; }

      if (payload.done && payload.segments) {
        document.getElementById('subtitle-progress-card').style.display = 'none';
        analyzeBtn.disabled = false;
        subtitleSegments = payload.segments;
        const vid = document.getElementById('subtitle-preview-video');
        if (uploadedFilename) vid.src = `/uploads/${encodeURIComponent(uploadedFilename)}`;
        document.getElementById('subtitle-editor-card').style.display = 'block';
        renderSubtitleSegments();
        document.getElementById('subtitle-editor-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
        showToast(`자막 ${payload.segments.length}개 생성 완료!`, 'success');
      } else if (payload.done) {
        document.getElementById('subtitle-progress-card').style.display = 'none';
        analyzeBtn.disabled = false;
        showToast('분석 완료됐으나 자막이 없습니다.', 'error');
      }
    });
  } catch {
    showToast('오류가 발생했습니다.', 'error');
    document.getElementById('subtitle-progress-card').style.display = 'none';
    analyzeBtn.disabled = false;
  }
});

function _secToSrtTime(sec) {
  const h  = Math.floor(sec / 3600);
  const m  = Math.floor((sec % 3600) / 60);
  const s  = Math.floor(sec % 60);
  const ms = Math.floor((sec % 1) * 1000);
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')},${String(ms).padStart(3,'0')}`;
}

function renderSubtitleSegments() {
  const wrap = document.getElementById('subtitle-segments-wrap');
  wrap.innerHTML = '';
  subtitleSegments.forEach(seg => {
    const row = document.createElement('div');
    row.className = 'subtitle-row';
    const ta = document.createElement('textarea');
    ta.className = 'subtitle-text-input';
    ta.rows = 1;
    ta.value = seg.text;
    ta.addEventListener('input', e => {
      seg.text = e.target.value;
      e.target.style.height = 'auto';
      e.target.style.height = e.target.scrollHeight + 'px';
    });
    const timing = document.createElement('div');
    timing.className = 'subtitle-timing';
    timing.title = '클릭하면 해당 시점으로 이동';
    timing.style.cursor = 'pointer';
    timing.textContent = `${_secToSrtTime(seg.start)}  →  ${_secToSrtTime(seg.end)}`;
    timing.addEventListener('click', () => {
      const vid = document.getElementById('subtitle-preview-video');
      if (vid) { vid.currentTime = seg.start; vid.play(); }
    });
    row.appendChild(timing);
    row.appendChild(ta);
    wrap.appendChild(row);
  });
  // 초기 높이 맞추기
  wrap.querySelectorAll('.subtitle-text-input').forEach(ta => {
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
  });
}

document.getElementById('subtitle-export-btn').addEventListener('click', async () => {
  if (!subtitleSegments.length) { showToast('자막 데이터가 없습니다.', 'error'); return; }
  const btn = document.getElementById('subtitle-export-btn');
  btn.disabled = true; btn.textContent = '⏳ 생성 중...';
  try {
    const res = await fetch('/subtitle/export-srt', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segments: subtitleSegments, filename_base: originalBase || 'subtitle' }),
    });
    const data = await res.json();
    if (data.ok) {
      const a = document.createElement('a');
      a.href = `/download/${encodeURIComponent(data.srt)}`; a.download = data.srt; a.click();
      showToast('SRT 다운로드 완료!', 'success');
    } else { showToast(data.error || 'SRT 생성 실패', 'error'); }
  } catch { showToast('오류가 발생했습니다.', 'error'); }
  finally { btn.disabled = false; btn.textContent = '📥 SRT 다운로드'; }
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
  uploadProgressWrap.style.display = 'none'; uploadProgressFill.style.width = '0%';
}

let toastTimer;
function showToast(msg, type = '') {
  clearTimeout(toastTimer);
  toast.textContent = msg; toast.className = 'show ' + type;
  toastTimer = setTimeout(() => { toast.className = ''; }, 3000);
}

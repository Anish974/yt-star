/* ═══════════════════════════════════════════════════════════════════════════
   YTStar — Client-Side Application Logic
   ═══════════════════════════════════════════════════════════════════════════ */

const API = '';  // Same origin

// ── State ──────────────────────────────────────────────────────────────────

const state = {
    videoInfo: null,
    audioOnly: false,
    selectedQuality: 'best',
    selectedFormatId: null,
    audioFormat: 'mp3',
    currentJobId: null,
    eventSource: null,
    fetching: false,  // guards against double-fetch (paste + Enter firing together)
};

// ── DOM References ─────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const dom = {
    urlInput: $('#url-input'),
    btnFetch: $('#btn-fetch'),
    themeToggle: $('#theme-toggle'),
    skeletonCard: $('#skeleton-card'),
    workspace: $('#workspace'),
    videoCard: $('#video-card'),
    videoThumbnail: $('#video-thumbnail'),
    videoDuration: $('#video-duration'),
    videoTitle: $('#video-title'),
    videoChannel: $('#video-channel'),
    videoViews: $('#video-views'),
    videoDate: $('#video-date'),
    videoExtractor: $('#video-extractor'),
    formatSection: $('#format-section'),
    formatSectionLabel: $('#format-section-label'),
    modeVideo: $('#mode-video'),
    modeAudio: $('#mode-audio'),
    qualityGrid: $('#quality-grid'),
    audioFormatRow: $('#audio-format-row'),
    audioFormatSelect: $('#audio-format'),
    downloadSection: $('#download-section'),
    btnDownload: $('#btn-download'),
    btnDownloadText: $('#btn-download-text'),
    progressSection: $('#progress-section'),
    progressBar: $('#progress-bar'),
    progressPercent: $('#progress-percent'),
    progressSpeed: $('#progress-speed'),
    progressEta: $('#progress-eta'),
    progressStatus: $('#progress-status'),
    progressError: $('#progress-error'),
    btnCancel: $('#btn-cancel'),
    btnSave: $('#btn-save'),
    emptyState: $('#empty-state'),
    toastContainer: $('#toast-container'),
};

// ── Theme (Light / Dark) ─────────────────────────────────────────────────

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    // Show the icon for the mode you'd switch TO.
    if (dom.themeToggle) dom.themeToggle.textContent = theme === 'light' ? '🌙' : '☀️';
}

function initTheme() {
    // The inline <head> script already set data-theme to avoid a flash —
    // just read it back and sync the toggle icon.
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current);
}

function toggleTheme() {
    const next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('ytstar-theme', next); } catch (e) { /* ignore */ }
    applyTheme(next);
}

// ── Utility Functions ──────────────────────────────────────────────────────

function formatBytes(bytes) {
    if (!bytes) return '';
    if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
    if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${bytes} B`;
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function formatNumber(num) {
    if (!num) return '';
    if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`;
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
    return num.toString();
}

function formatDate(dateStr) {
    if (!dateStr || dateStr.length !== 8) return '';
    const year = dateStr.slice(0, 4);
    const month = dateStr.slice(4, 6);
    const day = dateStr.slice(6, 8);
    const d = new Date(`${year}-${month}-${day}`);
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

// ── Toast Notifications ────────────────────────────────────────────────────

function showToast(message, type = 'error') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icon = type === 'error' ? '❌' : type === 'success' ? '✅' : 'ℹ️';
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${message}</span>
    `;
    dom.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toastOut 0.3s ease-in forwards';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ── Reset UI ───────────────────────────────────────────────────────────────

function resetUI() {
    if (dom.workspace) dom.workspace.classList.add('hidden');
    dom.videoCard.classList.add('hidden');
    dom.formatSection.classList.add('hidden');
    dom.downloadSection.classList.add('hidden');
    dom.progressSection.classList.add('hidden');
    dom.emptyState.classList.remove('hidden');
    dom.btnSave.classList.add('hidden');
    dom.progressError.classList.add('hidden');

    state.videoInfo = null;
    state.selectedQuality = 'best';
    state.selectedFormatId = null;
    state.currentJobId = null;

    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
}

// ── Fetch Video Info ───────────────────────────────────────────────────────

async function fetchInfo() {
    const url = dom.urlInput.value.trim();
    if (!url) {
        showToast('Please enter a URL');
        return;
    }

    // A paste auto-fetch and an Enter press can both fire — only resolve once.
    if (state.fetching) return;
    state.fetching = true;

    resetUI();
    dom.btnFetch.classList.add('loading');
    dom.btnFetch.disabled = true;
    dom.emptyState.classList.add('hidden');
    dom.skeletonCard.classList.remove('hidden');  // show placeholder while resolving

    try {
        // `&_=` cache-buster guarantees the browser never serves a stale
        // response when a different URL is fetched.
        const response = await fetch(
            `${API}/api/info?url=${encodeURIComponent(url)}&_=${Date.now()}`,
            { cache: 'no-store' }
        );
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Failed to fetch info' }));
            throw new Error(err.detail || 'Failed to fetch info');
        }
        const info = await response.json();

        state.videoInfo = info;
        renderVideoCard(info);
        renderFormatPicker(info);

        if (dom.workspace) dom.workspace.classList.remove('hidden');
        dom.downloadSection.classList.remove('hidden');

    } catch (err) {
        showToast(err.message);
        dom.emptyState.classList.remove('hidden');
    } finally {
        dom.btnFetch.classList.remove('loading');
        dom.btnFetch.disabled = false;
        dom.skeletonCard.classList.add('hidden');  // hide placeholder (success or fail)
        state.fetching = false;
    }
}

// ── Render Video Card ──────────────────────────────────────────────────────

function renderVideoCard(info) {
    dom.videoThumbnail.src = info.thumbnail || '';
    dom.videoThumbnail.alt = info.title;
    dom.videoDuration.textContent = info.duration_string || formatDuration(info.duration);
    dom.videoDuration.classList.toggle('hidden', !info.duration);
    dom.videoTitle.textContent = info.title;
    dom.videoChannel.textContent = info.channel || '';
    dom.videoViews.textContent = info.view_count ? `👁️ ${formatNumber(info.view_count)} views` : '';
    dom.videoDate.textContent = info.upload_date ? `📅 ${formatDate(info.upload_date)}` : '';
    dom.videoExtractor.textContent = info.extractor || '';
    dom.videoExtractor.classList.toggle('hidden', !info.extractor);

    dom.videoCard.classList.remove('hidden');
}

// ── Render Format Picker ───────────────────────────────────────────────────

function renderFormatPicker(info) {
    const formats = info.formats || [];

    // Build simplified quality options from available formats
    const qualityOptions = buildQualityOptions(formats);

    renderQualityGrid(qualityOptions);
    dom.formatSection.classList.remove('hidden');
}

function buildQualityOptions(formats) {
    // Group video formats by resolution
    const resolutions = new Map();

    for (const f of formats) {
        if (!f.has_video) continue;
        const match = (f.resolution || '').match(/(\d+)p?/);
        if (!match) continue;
        const height = parseInt(match[1]);
        if (height < 144) continue;

        const key = `${height}p`;
        const existing = resolutions.get(key);
        const size = f.filesize || f.filesize_approx || 0;

        if (!existing || size > (existing.size || 0)) {
            resolutions.set(key, {
                label: key,
                height,
                size,
                format_id: f.format_id,
                ext: f.ext,
                fps: f.fps,
                has_audio: f.has_audio,
            });
        }
    }

    // Sort by resolution descending
    const sorted = [...resolutions.values()].sort((a, b) => b.height - a.height);

    // Add "Best" option at top
    const options = [
        { label: 'Best', height: 9999, detail: 'Highest quality', isBest: true },
        ...sorted.map(r => ({
            label: r.label,
            height: r.height,
            detail: r.fps ? `${r.ext.toUpperCase()} • ${r.fps}fps` : r.ext.toUpperCase(),
            size: r.size,
            format_id: r.format_id,
        })),
    ];

    return options;
}

function renderQualityGrid(options) {
    if (state.audioOnly) {
        dom.qualityGrid.innerHTML = `
            <div class="quality-option selected" data-quality="best">
                <div class="quality-label">Best Audio</div>
                <div class="quality-detail">Highest bitrate</div>
            </div>
        `;
        return;
    }

    dom.qualityGrid.innerHTML = options.map((opt, i) => `
        <label class="quality-option ${i === 0 ? 'selected' : ''}" data-quality="${opt.isBest ? 'best' : opt.height}">
            <input type="radio" name="quality" value="${opt.isBest ? 'best' : opt.height}" ${i === 0 ? 'checked' : ''}>
            ${opt.isBest ? '<span class="quality-badge">Recommended</span>' : ''}
            <div class="quality-label">${opt.label}</div>
            <div class="quality-detail">${opt.detail || ''}</div>
            ${opt.size ? `<div class="quality-size">~${formatBytes(opt.size)}</div>` : ''}
        </label>
    `).join('');

    // Click handlers
    dom.qualityGrid.querySelectorAll('.quality-option').forEach(el => {
        el.addEventListener('click', () => {
            dom.qualityGrid.querySelectorAll('.quality-option').forEach(e => e.classList.remove('selected'));
            el.classList.add('selected');
            const radio = el.querySelector('input[type="radio"]');
            if (radio) radio.checked = true;
            state.selectedQuality = el.dataset.quality;
        });
    });
}

// ── Mode Toggle (Video / Audio) ────────────────────────────────────────────

dom.modeVideo.addEventListener('click', () => {
    state.audioOnly = false;
    dom.modeVideo.classList.add('active');
    dom.modeAudio.classList.remove('active');
    dom.audioFormatRow.classList.add('hidden');
    dom.formatSectionLabel.textContent = 'Choose Quality';
    dom.btnDownloadText.textContent = 'Download Video';

    // Re-render quality grid
    if (state.videoInfo) {
        renderFormatPicker(state.videoInfo);
    }
});

dom.modeAudio.addEventListener('click', () => {
    state.audioOnly = true;
    dom.modeAudio.classList.add('active');
    dom.modeVideo.classList.remove('active');
    dom.audioFormatRow.classList.remove('hidden');
    dom.formatSectionLabel.textContent = 'Audio Settings';
    dom.btnDownloadText.textContent = 'Download Audio';

    renderQualityGrid([]);
});

// Audio format change
dom.audioFormatSelect.addEventListener('change', () => {
    state.audioFormat = dom.audioFormatSelect.value;
});

// ── Start Download ─────────────────────────────────────────────────────────

async function startDownload() {
    const url = dom.urlInput.value.trim();
    if (!url) return;

    dom.btnDownload.disabled = true;
    dom.btnDownloadText.textContent = 'Starting...';

    try {
        const body = {
            url,
            audio_only: state.audioOnly,
            audio_format: state.audioFormat,
            // Sent so the backend can cache by video + quality.
            video_id: state.videoInfo?.id || null,
            title: state.videoInfo?.title || null,
        };

        if (!state.audioOnly) {
            if (state.selectedQuality === 'best') {
                body.quality = 'best';
            } else {
                body.quality = state.selectedQuality;
            }
        }

        const response = await fetch(`${API}/api/download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Failed to start download' }));
            throw new Error(err.detail || 'Failed to start download');
        }

        const { job_id } = await response.json();
        state.currentJobId = job_id;

        // Show progress UI
        dom.progressSection.classList.remove('hidden');
        dom.downloadSection.classList.add('hidden');
        dom.btnSave.classList.add('hidden');
        dom.progressError.classList.add('hidden');
        dom.btnCancel.classList.remove('hidden');
        dom.btnCancel.disabled = false;

        // Connect to SSE
        connectProgress(job_id);

    } catch (err) {
        showToast(err.message);
        dom.btnDownload.disabled = false;
        dom.btnDownloadText.textContent = state.audioOnly ? 'Download Audio' : 'Download Video';
    }
}

// ── Cancel Download ──────────────────────────────────────────────────────

async function cancelDownload() {
    const jobId = state.currentJobId;
    if (!jobId) return;

    dom.btnCancel.disabled = true;

    try {
        const response = await fetch(`${API}/api/cancel/${jobId}`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: 'Could not cancel' }));
            throw new Error(err.detail || 'Could not cancel');
        }
        // The backend flips the job to "cancelled"; the SSE stream will push the
        // final state and updateProgress() hides the button + re-enables download.
    } catch (err) {
        showToast(err.message);
        dom.btnCancel.disabled = false;
    }
}

// ── SSE Progress Stream ────────────────────────────────────────────────────

function connectProgress(jobId) {
    if (state.eventSource) {
        state.eventSource.close();
    }

    const es = new EventSource(`${API}/api/progress/${jobId}`);
    state.eventSource = es;

    es.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateProgress(data);

            if (['done', 'error', 'cancelled'].includes(data.status)) {
                es.close();
                state.eventSource = null;
            }
        } catch (err) {
            console.error('SSE parse error:', err);
        }
    };

    es.onerror = () => {
        // SSE will auto-reconnect, but if the job is done, close it
        const job = state.currentJobId;
        if (!job) {
            es.close();
            state.eventSource = null;
        }
    };
}

function updateProgress(data) {
    // Update progress bar
    const percent = Math.min(data.percent || 0, 100);
    dom.progressBar.style.width = `${percent}%`;
    dom.progressPercent.textContent = `${percent.toFixed(1)}%`;

    // Update speed & ETA
    dom.progressSpeed.textContent = data.speed ? `⚡ ${data.speed}` : '';
    dom.progressEta.textContent = data.eta ? `⏱️ ${data.eta}` : '';

    // Update status badge
    dom.progressStatus.className = `progress-status ${data.status}`;
    const statusLabels = {
        pending: 'Pending',
        downloading: 'Downloading',
        processing: 'Processing',
        done: 'Complete',
        error: 'Error',
        cancelled: 'Cancelled',
    };
    dom.progressStatus.textContent = statusLabels[data.status] || data.status;

    // Cancel only makes sense while the job is still active.
    const active = data.status === 'downloading' || data.status === 'processing' || data.status === 'pending';
    dom.btnCancel.classList.toggle('hidden', !active);

    if (data.status === 'done') {
        dom.progressBar.style.width = '100%';
        dom.progressPercent.textContent = '100%';
        dom.progressSpeed.textContent = '';
        dom.progressEta.textContent = '';

        // Show save button
        dom.btnSave.href = `${API}/api/file/${data.job_id}`;
        dom.btnSave.classList.remove('hidden');

        showToast('Download complete! Click "Save File" to save.', 'success');

        // Re-enable download button for new download
        dom.btnDownload.disabled = false;
        dom.btnDownloadText.textContent = state.audioOnly ? 'Download Audio' : 'Download Video';
        dom.downloadSection.classList.remove('hidden');
    }

    if (data.status === 'error') {
        dom.progressError.textContent = `Error: ${data.error || 'Unknown error'}`;
        dom.progressError.classList.remove('hidden');
        showToast(`Download failed: ${data.error}`, 'error');

        // Re-enable download button
        dom.btnDownload.disabled = false;
        dom.btnDownloadText.textContent = state.audioOnly ? 'Download Audio' : 'Download Video';
        dom.downloadSection.classList.remove('hidden');
    }

    if (data.status === 'cancelled') {
        showToast('Download cancelled', 'info');

        // Re-enable download button
        dom.btnDownload.disabled = false;
        dom.btnDownloadText.textContent = state.audioOnly ? 'Download Audio' : 'Download Video';
        dom.downloadSection.classList.remove('hidden');
    }
}

// ── Event Listeners ────────────────────────────────────────────────────────

// Fetch button
dom.btnFetch.addEventListener('click', fetchInfo);

// Download button
dom.btnDownload.addEventListener('click', startDownload);

// Cancel button
dom.btnCancel.addEventListener('click', cancelDownload);

// Enter key in URL input
dom.urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        e.preventDefault();
        fetchInfo();
    }
});

// Auto-detect paste
dom.urlInput.addEventListener('paste', () => {
    // Small delay to let the paste complete
    setTimeout(() => {
        const url = dom.urlInput.value.trim();
        if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
            fetchInfo();
        }
    }, 100);
});

// Keyboard shortcut: Ctrl+V focuses input
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'v') {
        if (document.activeElement !== dom.urlInput) {
            dom.urlInput.focus();
        }
    }
});

// Theme toggle
dom.themeToggle.addEventListener('click', toggleTheme);

// Initial state
initTheme();
dom.btnDownloadText.textContent = 'Download Video';

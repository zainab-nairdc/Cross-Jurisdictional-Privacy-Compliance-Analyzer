/**
 * app.js — Alpine.js init + WebSocket helpers + HTMX event hooks
 * Loaded at the bottom of base.html (section 3 of DESIGN.md).
 */

// ---------------------------------------------------------------------------
// HTMX configuration
// ---------------------------------------------------------------------------
document.addEventListener('htmx:configRequest', (e) => {
 // Attach CSRF token to every HTMX request
 e.detail.headers['X-CSRFToken'] = getCookie('csrftoken');
});

function getCookie(name) {
 const value = `; ${document.cookie}`;
 const parts = value.split(`; ${name}=`);
 if (parts.length === 2) return parts.pop().split(';').shift();
 return '';
}

// ---------------------------------------------------------------------------
// WebSocket — ingestion progress (section 10 of DESIGN.md)
// Called from ingestion_jobs.html when a job is active.
// ---------------------------------------------------------------------------
function connectIngestionSocket(jobId) {
 const ws = new WebSocket(`ws://${window.location.host}/ws/ingestion/${jobId}/`);

 ws.onmessage = (event) => {
 const data = JSON.parse(event.data);
 appendLogEntry(data.stage, data.message, data.timestamp);
 updateProgressBar(data.progress_pct);
 updateStageDots(data.current_stage);
 };

 ws.onclose = () => console.log(`[ingestion] WS closed for job ${jobId}`);
 ws.onerror = (err) => console.error('[ingestion] WS error', err);

 return ws;
}

function appendLogEntry(stage, message, timestamp) {
 const log = document.getElementById('ingestion-log');
 if (!log) return;
 const entry = document.createElement('p');
 entry.className = 'font-mono text-[11px] text-gray-600';
 entry.textContent = `[${timestamp}] Stage ${stage}: ${message}`;
 log.appendChild(entry);
 log.scrollTop = log.scrollHeight;
}

function updateProgressBar(pct) {
 const bar = document.getElementById('ingestion-progress');
 if (bar) bar.style.width = `${pct}%`;
}

function updateStageDots(currentStage) {
 document.querySelectorAll('[data-stage-dot]').forEach((dot) => {
 const stage = parseInt(dot.dataset.stageDot, 10);
 dot.classList.remove('bg-[#002583]', 'bg-[#002583]', 'bg-gray-300', 'animate-pulse');
 if (stage < currentStage) {
 dot.classList.add('bg-[#002583]'); // done — green
 } else if (stage === currentStage) {
 dot.classList.add('bg-[#002583]', 'animate-pulse'); // active — blue pulsing
 } else {
 dot.classList.add('bg-gray-300'); // pending — gray
 }
 });
}

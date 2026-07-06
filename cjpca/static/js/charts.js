/**
 * charts.js — Chart.js definitions for CJPCA analytics dashboard.
 * Uses ComparisonResult / ComparisonRun data from the analytics view.
 */

// ── Palette ───────────────────────────────────────────────────────────────────
const REL_COLORS = {
 equivalent: '#002583',
 stricter_in_a: '#002583',
 stricter_in_b: '#002583',
 additional_in_a: '#002583',
 additional_in_b: '#002583',
 conflicting: '#002583',
};

const PALETTE = {
 navy: '#002583',
 orange: '#002583',
 green: '#002583',
 red: '#002583',
 amber: '#002583',
 purple: '#002583',
 grey: '#002583',
};

// ── Shared defaults (set at init time, not module load, to avoid Chart undefined errors) ──
const SHARED = { responsive: true, maintainAspectRatio: false };

const TOOLTIP_STYLE = {
 backgroundColor: '#fff',
 borderColor: '#E5E8EF',
 borderWidth: 1,
 titleColor: '#002583',
 bodyColor: '#002583',
 padding: 10,
 cornerRadius: 8,
};

// ── Main init ─────────────────────────────────────────────────────────────────
function initComplianceCharts(data) {
 if (!data) return;
 if (typeof Chart === 'undefined') {
 console.error('CJPCA: Chart.js not loaded — charts cannot render');
 return;
 }

 Chart.defaults.font.family = "'Satoshi', sans-serif";
 Chart.defaults.font.size = 11;
 Chart.defaults.color = '#002583';

 tryInit('chart-relationship-donut', () => initRelationshipDonut(data.relationshipBreakdown));
 tryInit('chart-lifecycle', () => initLifecycleDonut(data.lifecycleStatus));
 tryInit('chart-relationship-by-pair', () => initRelationshipByPair(data.relationshipByPair));
 tryInit('chart-confidence-hist', () => initConfidenceHistogram(data.confidenceDistribution));
 tryInit('chart-avg-confidence', () => initAvgConfidenceByRel(data.avgConfidenceByRel));
 tryInit('chart-top-principles', () => initTopPrinciples(data.topPrinciples));
 tryInit('chart-runs-over-time', () => initRunsOverTime(data.runsOverTime));
 tryInit('chart-compliance-by-run', () => initComplianceByRun(data.complianceByRun));
 tryInit('chart-radar', () => initRadar(data.radar));
 tryInit('chart-gap-trend', () => initGapTrend(data.gapTrend));
 tryInit('chart-remediation-velocity', () => initRemediationVelocity(data.remediationVelocity));
 tryInit('chart-calibration', () => initCalibration(data.calibration));
 tryInit('chart-accuracy-trend', () => initAccuracyTrend(data.accuracyTrend));
}

function tryInit(id, fn) {
 const el = document.getElementById(id);
 if (!el) return;
 try { fn(); } catch (e) { console.warn('Chart init failed:', id, e); }
}

// ── Relationship breakdown — Doughnut ─────────────────────────────────────────
function initRelationshipDonut(data = {}) {
 const ctx = document.getElementById('chart-relationship-donut');
 if (!ctx || !data.values) return;

 const total = data.values.reduce((a, b) => a + b, 0);

 new Chart(ctx, {
 type: 'doughnut',
 data: {
 labels: data.labels,
 datasets: [{
 data: data.values,
 backgroundColor: data.colors,
 borderWidth: 2,
 borderColor: '#fff',
 hoverBorderWidth: 0,
 }],
 },
 options: {
 ...SHARED,
 cutout: '72%',
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: {
 label: (item) => {
 const v = item.raw;
 const pct = total ? Math.round(v / total * 100) : 0;
 return ` ${v} clauses (${pct}%)`;
 },
 },
 },
 },
 },
 plugins: [{
 id: 'center-text',
 afterDraw(chart) {
 if (!chart.chartArea) return;
 const { ctx: c, chartArea: { width, height, left, top } } = chart;
 const cx = left + width / 2;
 const cy = top + height / 2;
 c.save();
 c.textAlign = 'center';
 c.textBaseline = 'middle';
 c.fillStyle = '#002583';
 c.font = "700 26px 'Satoshi', sans-serif";
 c.fillText(total, cx, cy - 9);
 c.fillStyle = '#002583';
 c.font = "500 10px 'Nunito', sans-serif";
 c.fillText('clauses', cx, cy + 10);
 c.restore();
 },
 }],
 });
}

// ── Lifecycle status — Doughnut ───────────────────────────────────────────────
function initLifecycleDonut(data = {}) {
 const ctx = document.getElementById('chart-lifecycle');
 if (!ctx || !data.values) return;

 new Chart(ctx, {
 type: 'doughnut',
 data: {
 labels: data.labels,
 datasets: [{
 data: data.values,
 backgroundColor: ['#ffffff', '#002583', '#002583', '#002583'],
 borderWidth: 2,
 borderColor: '#fff',
 hoverBorderWidth: 0,
 }],
 },
 options: {
 ...SHARED,
 cutout: '68%',
 plugins: {
 legend: { display: false },
 tooltip: { ...TOOLTIP_STYLE },
 },
 },
 });
}

// ── Relationship by jurisdiction pair — Stacked Bar ───────────────────────────
function initRelationshipByPair(data = {}) {
 const ctx = document.getElementById('chart-relationship-by-pair');
 if (!ctx || !data.pairs) return;

 const relKeys = Object.keys(data.data || {});
 const datasets = relKeys.map((r, i) => ({
 label: data.labels[i] || r,
 data: data.data[r],
 backgroundColor: data.colors[i] || '#002583',
 borderRadius: i === relKeys.length - 1 ? { topLeft: 4, topRight: 4 } : 0,
 borderSkipped: false,
 }));

 new Chart(ctx, {
 type: 'bar',
 data: { labels: data.pairs, datasets },
 options: {
 ...SHARED,
 plugins: {
 legend: {
 position: 'bottom',
 labels: { boxWidth: 10, padding: 14, font: { size: 11 } },
 },
 tooltip: {
 ...TOOLTIP_STYLE,
 mode: 'index',
 intersect: false,
 callbacks: {
 footer: (items) => {
 const sum = items.reduce((a, i) => a + i.raw, 0);
 return `Total: ${sum} clauses`;
 },
 },
 },
 },
 scales: {
 x: {
 stacked: true,
 grid: { display: false },
 ticks: { font: { size: 11, weight: '600' } },
 },
 y: {
 stacked: true,
 grid: { color: '#ffffff' },
 ticks: { font: { size: 10, family: "'DM Mono', monospace" } },
 },
 },
 },
 });
}

// ── Confidence distribution — Histogram ───────────────────────────────────────
function initConfidenceHistogram(data = {}) {
 const ctx = document.getElementById('chart-confidence-hist');
 if (!ctx || !data.values) return;

 const colors = data.values.map((_, i) => {
 const pct = (i + 1) * 10;
 if (pct >= 80) return PALETTE.green + 'CC';
 if (pct >= 60) return PALETTE.amber + 'CC';
 return PALETTE.red + 'CC';
 });

 new Chart(ctx, {
 type: 'bar',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Clauses',
 data: data.values,
 backgroundColor: colors,
 borderRadius: 5,
 borderSkipped: false,
 }],
 },
 options: {
 ...SHARED,
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: {
 title: (items) => `Confidence: ${items[0].label}`,
 },
 },
 },
 scales: {
 x: {
 grid: { display: false },
 ticks: { font: { size: 9 }, maxRotation: 45 },
 },
 y: {
 grid: { color: '#ffffff' },
 ticks: { font: { size: 10, family: "'DM Mono', monospace" }, stepSize: 1 },
 },
 },
 },
 });
}

// ── Avg confidence by relationship — Horizontal Bar ───────────────────────────
function initAvgConfidenceByRel(data = {}) {
 const ctx = document.getElementById('chart-avg-confidence');
 if (!ctx || !data.values) return;

 new Chart(ctx, {
 type: 'bar',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Avg confidence %',
 data: data.values,
 backgroundColor: data.colors,
 borderRadius: 4,
 borderSkipped: false,
 }],
 },
 options: {
 ...SHARED,
 indexAxis: 'y',
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: { label: (i) => ` Avg: ${i.raw}%` },
 },
 },
 scales: {
 x: {
 max: 100,
 grid: { color: '#ffffff' },
 ticks: { callback: v => `${v}%`, font: { size: 9, family: "'DM Mono', monospace" } },
 },
 y: {
 grid: { display: false },
 ticks: { font: { size: 10 } },
 },
 },
 },
 });
}

// ── Top principles — Horizontal Bar ──────────────────────────────────────────
function initTopPrinciples(data = {}) {
 const ctx = document.getElementById('chart-top-principles');
 if (!ctx || !data.values) return;

 new Chart(ctx, {
 type: 'bar',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Clause count',
 data: data.values,
 backgroundColor: PALETTE.navy + 'BB',
 borderRadius: 4,
 borderSkipped: false,
 }],
 },
 options: {
 ...SHARED,
 indexAxis: 'y',
 plugins: {
 legend: { display: false },
 tooltip: { ...TOOLTIP_STYLE },
 },
 scales: {
 x: {
 grid: { color: '#ffffff' },
 ticks: { font: { size: 10, family: "'DM Mono', monospace" } },
 },
 y: {
 grid: { display: false },
 ticks: { font: { size: 10 } },
 },
 },
 },
 });
}

// ── Runs over time — Dual-axis Line ───────────────────────────────────────────
function initRunsOverTime(data = {}) {
 const ctx = document.getElementById('chart-runs-over-time');
 if (!ctx || !data.labels) return;

 new Chart(ctx, {
 type: 'line',
 data: {
 labels: data.labels,
 datasets: [
 {
 label: 'Completed runs',
 data: data.runs,
 borderColor: PALETTE.navy,
 backgroundColor: PALETTE.navy + '18',
 tension: 0.35,
 fill: true,
 pointRadius: 4,
 pointHoverRadius: 6,
 borderWidth: 2,
 yAxisID: 'y',
 },
 {
 label: 'Clause pairs analysed',
 data: data.results,
 borderColor: PALETTE.orange,
 backgroundColor: PALETTE.orange + '18',
 tension: 0.35,
 fill: true,
 pointRadius: 4,
 pointHoverRadius: 6,
 borderWidth: 2,
 yAxisID: 'y1',
 },
 ],
 },
 options: {
 ...SHARED,
 interaction: { mode: 'index', intersect: false },
 plugins: {
 legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14, font: { size: 11 } } },
 tooltip: { ...TOOLTIP_STYLE },
 },
 scales: {
 x: { grid: { display: false }, ticks: { font: { size: 10 } } },
 y: {
 position: 'left',
 grid: { color: '#ffffff' },
 ticks: { stepSize: 1, font: { size: 9, family: "'DM Mono', monospace" } },
 title: { display: true, text: 'Runs', font: { size: 9 }, color: '#002583' },
 },
 y1: {
 position: 'right',
 grid: { drawOnChartArea: false },
 ticks: { stepSize: 5, font: { size: 9, family: "'DM Mono', monospace" } },
 title: { display: true, text: 'Results', font: { size: 9 }, color: '#002583' },
 },
 },
 },
 });
}

// ── Compliance % per run — Line ───────────────────────────────────────────────
function initComplianceByRun(data = {}) {
 const ctx = document.getElementById('chart-compliance-by-run');
 if (!ctx || !data.labels) return;

 new Chart(ctx, {
 type: 'line',
 data: {
 labels: data.labels,
 datasets: [
 {
 label: 'Equivalent %',
 data: data.values,
 borderColor: PALETTE.green,
 backgroundColor: PALETTE.green + '18',
 tension: 0.3,
 fill: true,
 pointRadius: 4,
 pointHoverRadius: 6,
 borderWidth: 2,
 },
 {
 label: 'Target (100%)',
 data: data.labels.map(() => 100),
 borderColor: '#E5E8EF',
 borderDash: [5, 4],
 fill: false,
 pointRadius: 0,
 borderWidth: 1.5,
 },
 ],
 },
 options: {
 ...SHARED,
 interaction: { mode: 'index', intersect: false },
 plugins: {
 legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14, font: { size: 11 } } },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: { label: (i) => ` ${i.dataset.label}: ${i.raw}%` },
 },
 },
 scales: {
 x: { grid: { display: false }, ticks: { font: { size: 10 } } },
 y: {
 max: 100,
 grid: { color: '#ffffff' },
 ticks: { callback: v => `${v}%`, font: { size: 10, family: "'DM Mono', monospace" } },
 },
 },
 },
 });
}

// ── Radar — Coverage by principle ────────────────────────────────────────────
function initRadar(data = {}) {
 const ctx = document.getElementById('chart-radar');
 if (!ctx || !data.labels || !data.labels.length) return;

 new Chart(ctx, {
 type: 'radar',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Equivalent %',
 data: data.values,
 borderColor: '#002583',
 backgroundColor: 'rgba(83,74,183,0.12)',
 pointBackgroundColor: '#002583',
 pointRadius: 3,
 borderWidth: 2,
 }],
 },
 options: {
 ...SHARED,
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: { label: (i) => ` Equivalent: ${i.raw}%` },
 },
 },
 scales: {
 r: {
 min: 0, max: 100,
 ticks: {
 stepSize: 25,
 callback: v => `${v}%`,
 font: { size: 9 },
 color: '#002583',
 backdropColor: 'transparent',
 },
 pointLabels: { font: { size: 11, family: "'Satoshi', sans-serif" }, color: '#002583' },
 grid: { color: '#ffffff' },
 angleLines: { color: '#ffffff' },
 },
 },
 },
 });
}

// ── Gap trend — Conflicts identified vs Approvals resolved ────────────────────
function initGapTrend(data = {}) {
 const ctx = document.getElementById('chart-gap-trend');
 if (!ctx || !data.labels) return;

 new Chart(ctx, {
 type: 'line',
 data: {
 labels: data.labels,
 datasets: [
 {
 label: 'Conflicts identified',
 data: data.identified,
 borderColor: PALETTE.red,
 backgroundColor: PALETTE.red + '15',
 tension: 0.35,
 fill: true,
 pointRadius: 4,
 pointHoverRadius: 6,
 borderWidth: 2,
 },
 {
 label: 'Clauses approved',
 data: data.resolved,
 borderColor: PALETTE.green,
 backgroundColor: PALETTE.green + '15',
 tension: 0.35,
 fill: true,
 pointRadius: 4,
 pointHoverRadius: 6,
 borderWidth: 2,
 },
 ],
 },
 options: {
 ...SHARED,
 interaction: { mode: 'index', intersect: false },
 plugins: {
 legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14, font: { size: 11 } } },
 tooltip: { ...TOOLTIP_STYLE },
 },
 scales: {
 x: { grid: { display: false }, ticks: { font: { size: 10 } } },
 y: {
 grid: { color: '#ffffff' },
 ticks: { stepSize: 1, font: { size: 10, family: "'DM Mono', monospace" } },
 },
 },
 },
 });
}

// ── Remediation velocity — Approvals per week ─────────────────────────────────
function initRemediationVelocity(data = {}) {
 const ctx = document.getElementById('chart-remediation-velocity');
 if (!ctx || !data.labels) return;

 new Chart(ctx, {
 type: 'bar',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Approvals',
 data: data.values,
 backgroundColor: data.values.map(v => v > 0 ? PALETTE.green + 'CC' : '#ffffff'),
 borderRadius: 5,
 borderSkipped: false,
 }],
 },
 options: {
 ...SHARED,
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: { label: (i) => ` ${i.raw} approval${i.raw !== 1 ? 's' : ''}` },
 },
 },
 scales: {
 x: { grid: { display: false }, ticks: { font: { size: 10 } } },
 y: {
 grid: { color: '#ffffff' },
 ticks: { stepSize: 1, font: { size: 10, family: "'DM Mono', monospace" } },
 },
 },
 },
 });
}

// ── Confidence calibration — grouped bar ──────────────────────────────────────
function initCalibration(data = {}) {
 const ctx = document.getElementById('chart-calibration');
 if (!ctx || !data.labels) return;

 // Null slots → skip rendering (no data for that bucket)
 const hasAny = data.actual && data.actual.some(v => v !== null);

 new Chart(ctx, {
 type: 'bar',
 data: {
 labels: data.labels,
 datasets: [
 {
 label: 'AI confidence (expected)',
 data: data.ai_conf,
 backgroundColor: '#1B306822',
 borderColor: '#1B306855',
 borderWidth: 1,
 borderRadius: 4,
 borderSkipped: false,
 },
 {
 label: 'Human approval rate (actual)',
 data: hasAny ? data.actual : [],
 backgroundColor: '#faa63399',
 borderColor: '#002583',
 borderWidth: 1,
 borderRadius: 4,
 borderSkipped: false,
 },
 ],
 },
 options: {
 ...SHARED,
 plugins: {
 legend: {
 display: true,
 position: 'bottom',
 labels: { font: { size: 9 }, boxWidth: 10, padding: 10 },
 },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: {
 label: (i) => {
 if (i.datasetIndex === 0) return ` AI claimed: ${i.raw}%`;
 const count = data.counts && data.counts[i.dataIndex];
 return ` Reviewers agreed: ${i.raw ?? '—'}%${count ? ` (${count} reviews)` : ''}`;
 },
 },
 },
 },
 scales: {
 x: {
 grid: { display: false },
 ticks: { font: { size: 9 }, maxRotation: 30 },
 },
 y: {
 min: 0, max: 100,
 grid: { color: '#ffffff' },
 ticks: {
 stepSize: 20,
 font: { size: 9, family: "'DM Mono', monospace" },
 callback: (v) => v + '%',
 },
 },
 },
 },
 });
}

// ── Monthly accuracy trend — line ─────────────────────────────────────────────
function initAccuracyTrend(data = {}) {
 const ctx = document.getElementById('chart-accuracy-trend');
 if (!ctx || !data.labels) return;

 new Chart(ctx, {
 type: 'line',
 data: {
 labels: data.labels,
 datasets: [{
 label: 'Approval rate',
 data: data.values,
 borderColor: '#002583',
 backgroundColor: '#faa63322',
 borderWidth: 2,
 pointRadius: 4,
 pointBackgroundColor: '#002583',
 tension: 0.35,
 fill: true,
 spanGaps: true,
 }],
 },
 options: {
 ...SHARED,
 plugins: {
 legend: { display: false },
 tooltip: {
 ...TOOLTIP_STYLE,
 callbacks: {
 label: (i) => i.raw !== null ? ` ${i.raw}% approved` : ' No data',
 },
 },
 },
 scales: {
 x: { grid: { display: false }, ticks: { font: { size: 10 } } },
 y: {
 min: 0, max: 100,
 grid: { color: '#ffffff' },
 ticks: {
 stepSize: 25,
 font: { size: 9, family: "'DM Mono', monospace" },
 callback: (v) => v + '%',
 },
 },
 },
 },
 });
}

// ── Utility: count-up animation (called from template, not auto-wired) ────────
function animateCountUp(el, target, suffix = '') {
 const duration = 900;
 const start = performance.now();
 const update = (now) => {
 const t = Math.min((now - start) / duration, 1);
 const ease = 1 - Math.pow(1 - t, 3);
 el.textContent = Math.round(target * ease) + suffix;
 if (t < 1) requestAnimationFrame(update);
 };
 requestAnimationFrame(update);
}

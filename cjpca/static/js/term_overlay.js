/**
 * term_overlay.js — Alpine.js component for Visual 8: Term Frequency / Semantic Overlay.
 *
 * Usage in template:
 * <div x-data="termOverlay()"> ... </div>
 *
 * Concept highlighting is rendered server-side. This component manages:
 * - overlay toggle (show / hide colored backgrounds via CSS class)
 * - hover effects (outline active concept spans, dim others)
 */

function termOverlay() {
 return {
 overlayOn: true,

 // ── Overlay toggle ─────────────────────────────────────────────────────────

 toggleOverlay() {
 this.overlayOn = !this.overlayOn;
 // The :class="{ 'overlay-off': !overlayOn }" on the container drives CSS
 // which suppresses .concept-span inline styles — no manual DOM needed.
 },

 // ── Concept hover effects ──────────────────────────────────────────────────

 /**
 * Dims all concept spans except those matching conceptId, which get an outline.
 *
 * @param {string} conceptId - data-concept attribute value to highlight
 * @param {string} dotColor - color_dot for the outline (e.g. "#002583")
 */
 hoverConcept(conceptId, dotColor) {
 document.querySelectorAll('.concept-span').forEach(span => {
 if (span.dataset.concept === conceptId) {
 span.style.outline = `1px solid ${dotColor}`;
 span.style.opacity = '1';
 } else {
 span.style.outline = '';
 span.style.opacity = '0.4';
 }
 });
 },

 unhoverConcept() {
 document.querySelectorAll('.concept-span').forEach(span => {
 span.style.outline = '';
 span.style.opacity = '1';
 });
 },
 };
}

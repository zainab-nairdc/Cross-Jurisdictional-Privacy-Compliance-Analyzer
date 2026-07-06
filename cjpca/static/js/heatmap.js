/**
 * heatmap.js — Alpine.js component for the Coverage Heatmap.
 *
 * Usage: x-data="coverageHeatmap()" on the heatmap wrapper element.
 *
 * Responsibilities:
 * - Track which cell is selected (selectedPrinciple / selectedJurisdiction)
 * - On cell click: fire HTMX to update #gap-register, or clear if re-clicked
 * - Expose isSelected(p, j) for :data-selected bindings
 * - Optionally update window.currentContext for Copilot
 *
 * No hex colours. No inline styles. No chart libraries.
 */
function coverageHeatmap() {
 return {
 selectedPrinciple: null,
 selectedJurisdiction: null,

 isSelected(principle, jurisdiction) {
 return (
 this.selectedPrinciple === principle &&
 this.selectedJurisdiction === jurisdiction
 );
 },

 handleCellClick(el) {
 const ds = el.dataset;
 const p = ds.principle;
 const j = ds.jurisdiction;

 if (this.isSelected(p, j)) {
 // Second click on same cell → clear filter
 this.selectedPrinciple = null;
 this.selectedJurisdiction = null;
 htmx.ajax('GET', '/analytics/gaps/', {
 target: '#gap-register',
 swap: 'innerHTML',
 });
 if (typeof window.currentContext !== 'undefined') {
 window.currentContext = null;
 }
 } else {
 this.selectedPrinciple = p;
 this.selectedJurisdiction = j;
 const url = (
 '/analytics/gaps/'
 + '?jurisdiction=' + encodeURIComponent(j)
 + '&principle=' + encodeURIComponent(p)
 );
 htmx.ajax('GET', url, {
 target: '#gap-register',
 swap: 'innerHTML',
 });
 // Propagate context to Copilot if the global is available
 if (typeof window.currentContext !== 'undefined') {
 const pct = ds.pct ? ds.pct + '% covered' : 'no data';
 window.currentContext = ds.jurLabel + ' × ' + ds.principleLabel + ': ' + pct;
 }
 }
 },
 };
}

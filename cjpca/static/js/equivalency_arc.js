/**
 * equivalency_arc.js — Alpine.js component for the Equivalency Arc Diagram.
 */

function equivalencyArc() {
 return {
 hoveredArc: null,
 hoveredArticle: null,
 selectedArticle: null, // { id, label, side }
 _arcs: [],
 _articleMap: {}, // id → { label, short, side }
 _regAName: '',
 _regBName: '',

 init() {
 // Read reg names from data attributes on root element
 this._regAName = this.$el.dataset.regA || '';
 this._regBName = this.$el.dataset.regB || '';

 // Parse JSON data from <script type="application/json"> tags
 try {
 const arcsEl = document.getElementById('arc-data-json');
 const artAEl = document.getElementById('articles-a-json');
 const artBEl = document.getElementById('articles-b-json');

 if (arcsEl) this._arcs = JSON.parse(arcsEl.textContent);

 const map = {};
 if (artAEl) JSON.parse(artAEl.textContent).forEach(a => {
 map[a.id] = { label: a.label, short: a.short_label, side: 'a' };
 });
 if (artBEl) JSON.parse(artBEl.textContent).forEach(a => {
 map[a.id] = { label: a.label, short: a.short_label, side: 'b' };
 });
 this._articleMap = map;
 } catch (e) {
 console.warn('Arc diagram: failed to parse data', e);
 }
 },

 // ── Arc interactions ────────────────────────────────────────────────────

 onArcHover(arcId, tooltip) {
 this.hoveredArc = arcId;
 if (this.$refs.tooltip) this.$refs.tooltip.textContent = tooltip;
 },

 onArcLeave() {
 this.hoveredArc = null;
 if (this.$refs.tooltip) this.$refs.tooltip.textContent = 'Hover an arc to see details';
 },

 onArcClick(arcId) {
 window.dispatchEvent(new CustomEvent('arc:selected', { detail: { arcId } }));
 },

 // ── Article interactions ────────────────────────────────────────────────

 onArticleHover(articleId) {
 this.hoveredArticle = articleId;
 },

 onArticleLeave() {
 this.hoveredArticle = null;
 },

 onArticleClick(articleId, label, side) {
 // Toggle: click same article again to deselect
 if (this.selectedArticle && this.selectedArticle.id === articleId) {
 this.selectedArticle = null;
 } else {
 this.selectedArticle = { id: articleId, label, side };
 }
 },

 closeDetail() {
 this.selectedArticle = null;
 },

 // ── Derived state ───────────────────────────────────────────────────────

 isSelected(articleId) {
 return !!(this.selectedArticle && this.selectedArticle.id === articleId);
 },

 arcOpacity(sourceId, targetId) {
 const activeId = this.selectedArticle
 ? this.selectedArticle.id
 : this.hoveredArticle;
 if (!activeId) return 1;
 return (sourceId === activeId || targetId === activeId) ? 1 : 0.08;
 },

 connectedArcs() {
 if (!this.selectedArticle) return [];
 const id = this.selectedArticle.id;
 return this._arcs
 .filter(a => a.source_article_id === id || a.target_article_id === id)
 .map(a => {
 const otherId = a.source_article_id === id ? a.target_article_id : a.source_article_id;
 const other = this._articleMap[otherId] || {};
 return {
 ...a,
 other_label: other.label || otherId,
 other_short: other.short || otherId,
 };
 });
 },

 relLabel(rel) {
 const map = {
 equivalent: 'Equivalent',
 stricter_in_a: 'Stricter A',
 stricter_in_b: 'Stricter B',
 additional_in_a: 'Additional A',
 additional_in_b: 'Additional B',
 conflicting: 'Conflicting',
 };
 return map[rel] || rel;
 },
 };
}

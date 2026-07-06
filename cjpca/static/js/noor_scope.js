function getCsrfToken() {
 const name = 'csrftoken';
 const cookies = document.cookie.split(';');
 for (let c of cookies) {
 c = c.trim();
 if (c.startsWith(name + '=')) return decodeURIComponent(c.slice(name.length + 1));
 }
 return '';
}

function copilotScope(initialState) {
 return {
 state: initialState,
 toggling: false,

 init() {
 window.addEventListener('copilot:scope_refresh_needed', () => this.refresh());
 window.addEventListener('lifecycle:transitioned', () => this.refresh());
 window.addEventListener('document:ingested', () => this.refresh());
 },

 get dotColor() {
 return ({
 ready: '#002583',
 partially_ready: '#002583',
 not_ready: '#002583',
 })[this.state.state] || '#002583';
 },

 get showRail() { return this.state.state !== 'ready'; },
 get showFraction() { return this.state.state !== 'ready'; },
 get showActions() {
 if (!this.state.actions) return false;
 return (
 this.state.actions.review_drafts.enabled ||
 this.state.actions.include_drafts_toggle.visible
 );
 },

 async refresh() {
 try {
 const res = await fetch('/copilot/scope/');
 if (res.ok) this.state = await res.json();
 } catch (_) {}
 },

 async toggleDrafts() {
 if (this.toggling) return;
 this.toggling = true;
 const next = !this.state.actions.include_drafts_toggle.current;
 this.state.actions.include_drafts_toggle.current = next;
 try {
 const res = await fetch('/copilot/scope/preferences/', {
 method: 'PATCH',
 headers: {
 'Content-Type': 'application/json',
 'X-CSRFToken': getCsrfToken(),
 },
 body: JSON.stringify({ include_drafts: next }),
 });
 if (!res.ok) throw new Error('Failed');
 window.dispatchEvent(
 new CustomEvent('copilot:include_drafts_changed', { detail: { value: next } })
 );
 } catch (_) {
 this.state.actions.include_drafts_toggle.current = !next;
 } finally {
 this.toggling = false;
 }
 },
 };
}

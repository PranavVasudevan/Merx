// D7 — minimal, safe markdown-lite renderer for analyst annotations: bold,
// italic and links only. No dependency pulled in for this; the surface is
// small enough to hand-write safely (escape first, THEN apply markup, so a
// note's own text can never inject HTML).
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function renderMarkdownLite(raw: string): string {
  let html = escapeHtml(raw);
  // [text](https://...) — href restricted to http(s) so a note can't produce
  // a javascript: link.
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/\n/g, '<br/>');
  return html;
}

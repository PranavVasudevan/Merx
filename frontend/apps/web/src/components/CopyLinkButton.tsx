import { useState } from 'react';
import './CopyLinkButton.css';

/** D8 — "copy link to this view": copies the full current URL (path + search
 * params), so any page that keeps its state in the URL becomes shareable. */
export function CopyLinkButton() {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard permission denied or unavailable — silently no-op, the
      // button just doesn't confirm rather than throwing at the user
    }
  }

  return (
    <button type="button" className="copy-link-btn" onClick={copy} title="Copy a link that reproduces this exact view">
      {copied ? '✓ Copied' : '🔗 Copy link'}
    </button>
  );
}

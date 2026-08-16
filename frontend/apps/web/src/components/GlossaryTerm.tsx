import { useState } from 'react';
import { GLOSSARY_BY_KEY } from '../glossary';
import './GlossaryTerm.css';

/** D14 — hover/click definition affordance for a metric label. Wraps its
 * children (the label text) and shows the glossary entry's definition,
 * formula, source field and why-it-matters on hover/focus/click. */
export function GlossaryTerm({ termKey, children }: { termKey: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const entry = GLOSSARY_BY_KEY[termKey];
  if (!entry) return <>{children}</>;

  return (
    <span
      className="glossary-term"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onClick={() => setOpen((v) => !v)}
      tabIndex={0}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      <span className="glossary-term-mark" aria-hidden="true">ⓘ</span>
      {open && (
        <span className="glossary-term-popover" role="tooltip">
          <strong>{entry.label}</strong>
          <span className="glossary-term-def">{entry.definition}</span>
          <span className="glossary-term-formula">{entry.formula}</span>
          <span className="glossary-term-source">Source: {entry.source_field}</span>
          <span className="glossary-term-why">{entry.why_it_matters}</span>
        </span>
      )}
    </span>
  );
}

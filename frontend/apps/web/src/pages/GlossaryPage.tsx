import { GLOSSARY } from '../glossary';
import './GlossaryPage.css';

/** D14 — standalone glossary page: every term's definition, formula, source
 * field and why it matters, in one place (same data GlossaryTerm's
 * hover/click affordance reads inline). */
export function GlossaryPage() {
  return (
    <div className="glossary-page">
      <div className="panel">
        <h2>Glossary</h2>
        <p className="muted glossary-subtitle">
          Every term used across the product, with its formula, source field and why it matters —
          the same content the ⓘ hover affordance shows inline next to a metric label.
        </p>
      </div>
      {GLOSSARY.map((e) => (
        <div className="panel" key={e.key} id={e.key}>
          <h3 className="glossary-entry-label">{e.label}</h3>
          <p className="glossary-entry-def">{e.definition}</p>
          <dl className="glossary-entry-dl">
            <dt>Formula</dt>
            <dd className="glossary-entry-formula">{e.formula}</dd>
            <dt>Source field</dt>
            <dd>{e.source_field}</dd>
            <dt>Why it matters</dt>
            <dd>{e.why_it_matters}</dd>
          </dl>
        </div>
      ))}
    </div>
  );
}

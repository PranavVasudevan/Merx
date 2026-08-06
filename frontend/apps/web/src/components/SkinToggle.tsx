import { useEffect, useState } from 'react';
import { getSkin, setSkin, type Skin } from '../skin';

// Cycles classic <-> terminal. Tailwind-styled (not a .css file) since this is new
// chrome, not a re-skin of an existing component — but every color it uses is a
// token (bg-surface-2, text-secondary, ...) so it looks native under both skins
// without any skin-specific className branching.
export function SkinToggle() {
  const [skin, setSkinState] = useState<Skin>('classic');

  useEffect(() => {
    setSkinState(getSkin());
  }, []);

  function toggle() {
    const next: Skin = skin === 'classic' ? 'terminal' : 'classic';
    setSkin(next);
    setSkinState(next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      title={skin === 'classic' ? 'Switch to Terminal skin' : 'Switch to Classic skin'}
      className="inline-flex items-center gap-1.5 rounded-panel-pill border border-border
                 bg-surface-2 px-2.5 py-1 text-xs font-semibold text-secondary
                 transition-colors hover:border-border-strong hover:text-primary"
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 rounded-full ${skin === 'terminal' ? 'bg-cat-aqua' : 'bg-cat-blue'}`}
      />
      {skin === 'classic' ? 'Classic' : 'Terminal'}
    </button>
  );
}

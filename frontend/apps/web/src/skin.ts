// Two visual skins, not two apps: "classic" is the current Stripe-inspired
// restrained theme (theme.css, prefers-color-scheme light/dark), "terminal" is the
// dark glassmorphism "quant terminal" look (skin-terminal.css). Both read the exact
// same DOM/components — the skin only changes what the shared CSS custom properties
// resolve to (see theme.css .panel + skin-terminal.css), so no page needed to be
// rewritten to support a second look.
export type Skin = 'classic' | 'terminal';

const STORAGE_KEY = 'banklens-skin';
export const SKIN_CHANGE_EVENT = 'banklens:skinchange';

export function getSkin(): Skin {
  if (typeof window === 'undefined') return 'classic';
  return window.localStorage.getItem(STORAGE_KEY) === 'terminal' ? 'terminal' : 'classic';
}

export function setSkin(skin: Skin): void {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(STORAGE_KEY, skin);
  document.documentElement.dataset.skin = skin;
  window.dispatchEvent(new CustomEvent(SKIN_CHANGE_EVENT, { detail: skin }));
}

/** Call once at startup (main.tsx) to apply whatever skin was last chosen. */
export function initSkin(): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset.skin = getSkin();
}

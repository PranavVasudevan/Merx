import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// chartColors() memoizes its result in a module-level `cached` variable with
// no exposed reset, so each test that cares about a fresh read needs its own
// module instance — vi.resetModules() + a dynamic re-import gets one.
async function freshColors() {
  vi.resetModules();
  return import('./colors');
}

beforeEach(() => {
  document.documentElement.style.cssText = '';
  document.documentElement.removeAttribute('data-skin');
  delete document.documentElement.dataset.skin;
});

afterEach(() => {
  document.documentElement.style.cssText = '';
});

describe('isDarkMode', () => {
  it('is false by default (jsdom has no matchMedia and no terminal skin)', async () => {
    const { isDarkMode } = await freshColors();
    expect(isDarkMode()).toBe(false);
  });

  it('is true when the terminal skin is active, regardless of matchMedia', async () => {
    document.documentElement.dataset.skin = 'terminal';
    const { isDarkMode } = await freshColors();
    expect(isDarkMode()).toBe(true);
  });
});

describe('chartColors token resolution', () => {
  it('falls back to the hardcoded light palette when theme.css tokens are unset', async () => {
    const { chartColors } = await freshColors();
    const c = chartColors();
    // No stylesheet is loaded in this test environment, so every
    // getPropertyValue() read comes back '' and every key must fall through
    // to FALLBACK_LIGHT (isDarkMode() is false here).
    expect(c.blue).toBe('#2a78d6');
    expect(c.surface).toBe('#ffffff');
    expect(c.critical).toBe('#d03b3b');
  });

  it('falls back to the dark palette when the terminal skin is active', async () => {
    document.documentElement.dataset.skin = 'terminal';
    const { chartColors } = await freshColors();
    const c = chartColors();
    expect(c.blue).toBe('#3987e5');
    expect(c.surface).toBe('#1c1c1b');
  });

  it('prefers a real computed custom property over the fallback when one is set', async () => {
    document.documentElement.style.setProperty('--cat-blue', '#123456');
    const { chartColors } = await freshColors();
    const c = chartColors();
    expect(c.blue).toBe('#123456');
    // Untouched tokens still fall back normally alongside the overridden one.
    expect(c.critical).toBe('#d03b3b');
  });

  it('memoizes across calls until a theme-change event clears the cache', async () => {
    const { chartColors, onThemeChange } = await freshColors();
    const first = chartColors();
    document.documentElement.style.setProperty('--cat-blue', '#abcdef');
    const second = chartColors();
    expect(second.blue).toBe(first.blue); // still cached, the live style change is ignored

    const cb = vi.fn();
    const unsubscribe = onThemeChange(cb);
    window.dispatchEvent(new Event('banklens:skinchange'));
    expect(cb).toHaveBeenCalledTimes(1);
    const third = chartColors();
    expect(third.blue).toBe('#abcdef'); // cache was invalidated, so the new value is picked up
    unsubscribe();
  });
});

describe('resemblanceZone', () => {
  it('reports "Not ranked" for a null percentile', async () => {
    const { resemblanceZone, chartColors } = await freshColors();
    const c = chartColors();
    expect(resemblanceZone(null)).toEqual({ color: c.muted, label: 'Not ranked' });
  });

  it('buckets at the documented 90/70 thresholds', async () => {
    const { resemblanceZone, chartColors } = await freshColors();
    const c = chartColors();
    expect(resemblanceZone(95)).toEqual({ color: c.critical, label: 'High resemblance' });
    expect(resemblanceZone(90)).toEqual({ color: c.critical, label: 'High resemblance' });
    expect(resemblanceZone(75)).toEqual({ color: c.warning, label: 'Moderate resemblance' });
    expect(resemblanceZone(70)).toEqual({ color: c.warning, label: 'Moderate resemblance' });
    expect(resemblanceZone(10)).toEqual({ color: c.good, label: 'Low resemblance' });
  });
});

describe('categoricalPalette / sequentialRamp', () => {
  it('returns the 8 categorical tokens in the documented fixed order', async () => {
    const { categoricalPalette, chartColors } = await freshColors();
    const c = chartColors();
    expect(categoricalPalette()).toEqual([c.blue, c.green, c.magenta, c.yellow, c.aqua, c.orange, c.violet, c.red]);
  });

  it('returns the 4-step sequential ramp light-to-dark', async () => {
    const { sequentialRamp, chartColors } = await freshColors();
    const c = chartColors();
    expect(sequentialRamp()).toEqual([c.seq100, c.seq300, c.seq450, c.seq600]);
  });
});

import { describe, expect, it } from 'vitest';
import { fmtAssets, pct, ratio, usd } from './metricFormat';

describe('pct', () => {
  it('formats a number with the default 2 decimals', () => {
    expect(pct(12.345)).toBe('12.35%');
  });

  it('honors a custom decimals count', () => {
    expect(pct(12.345, 0)).toBe('12%');
  });

  it('formats zero as 0.00%, not the null placeholder', () => {
    expect(pct(0)).toBe('0.00%');
  });

  it('keeps the sign on negative values', () => {
    expect(pct(-3.5)).toBe('-3.50%');
  });

  it('renders null/undefined as the em-dash placeholder', () => {
    expect(pct(null)).toBe('—');
    expect(pct(undefined as unknown as null)).toBe('—');
  });

  it('passes a string value through unchanged', () => {
    expect(pct('n/a')).toBe('n/a');
  });
});

describe('usd', () => {
  it('abbreviates billions', () => {
    expect(usd(2_500_000_000)).toBe('$2.50B');
  });

  it('abbreviates millions', () => {
    expect(usd(4_200_000)).toBe('$4.2M');
  });

  it('uses locale grouping under the millions threshold', () => {
    expect(usd(950_000)).toBe('$950,000');
  });

  it('formats zero as a plain dollar amount, not the placeholder', () => {
    expect(usd(0)).toBe('$0');
  });

  it('abbreviates negative billions using the magnitude, keeping the sign', () => {
    expect(usd(-2_500_000_000)).toBe('$-2.50B');
  });

  it('renders null/undefined/non-numeric as the em-dash placeholder', () => {
    expect(usd(null)).toBe('—');
    expect(usd(undefined as unknown as null)).toBe('—');
    expect(usd('n/a')).toBe('—');
  });
});

describe('fmtAssets', () => {
  it('renders assets at or above 1B in billions with 1 decimal', () => {
    expect(fmtAssets(1_000_000_000)).toBe('$1.0B');
    expect(fmtAssets(3_400_000_000)).toBe('$3.4B');
  });

  it('renders assets under 1B in whole millions', () => {
    expect(fmtAssets(250_000_000)).toBe('$250M');
  });

  it('treats zero as under the billion threshold', () => {
    expect(fmtAssets(0)).toBe('$0M');
  });

  it('renders null/undefined/non-numeric as the em-dash placeholder', () => {
    expect(fmtAssets(null)).toBe('—');
    expect(fmtAssets(undefined as unknown as null)).toBe('—');
    expect(fmtAssets('n/a')).toBe('—');
  });
});

describe('ratio', () => {
  it('formats with 2 decimals and the default x suffix', () => {
    expect(ratio(1.5)).toBe('1.50x');
  });

  it('honors a custom suffix', () => {
    expect(ratio(1.5, '×')).toBe('1.50×');
  });

  it('formats zero rather than treating it as missing', () => {
    expect(ratio(0)).toBe('0.00x');
  });

  it('keeps the sign on a negative ratio', () => {
    expect(ratio(-0.25)).toBe('-0.25x');
  });

  it('renders null/undefined as the em-dash placeholder', () => {
    expect(ratio(null)).toBe('—');
    expect(ratio(undefined as unknown as null)).toBe('—');
  });

  it('passes a string value through unchanged', () => {
    expect(ratio('n/a')).toBe('n/a');
  });
});

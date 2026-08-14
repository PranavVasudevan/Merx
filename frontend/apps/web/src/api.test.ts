import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getCurrentUser = vi.fn();
vi.mock('./auth', () => ({ getCurrentUser: () => getCurrentUser() }));

// BASE falls back to the local dev bridge (see api.ts) since VITE_API_BASE
// isn't set for the test run.
const BASE = 'http://localhost:8791/api';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number; statusText?: string } = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? 'OK',
    json: () => Promise.resolve(body),
  } as Response;
}

describe('api', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    getCurrentUser.mockReset();
    getCurrentUser.mockResolvedValue(null);
    fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: 'ok' }));
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  describe('query-string construction', () => {
    it('omits undefined and empty-string params, keeps the rest', async () => {
      const { api } = await import('./api');
      await api.screenBanks({ query: undefined, state: 'NY', country: '', min_assets_b: 5 });
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toBe(`${BASE}/banks?state=NY&min_assets_b=5&limit=50`);
    });

    it('URL-encodes param values', async () => {
      const { api } = await import('./api');
      await api.screenBanks({ query: 'Bank & Trust' });
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toContain(`query=${encodeURIComponent('Bank & Trust')}`);
    });

    it('produces no "?" at all when every param is filtered out', async () => {
      const { api } = await import('./api');
      await api.health();
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toBe(`${BASE}/health`);
    });

    it('joins a certs array into one comma-separated query value (no repeated-key param)', async () => {
      const { api } = await import('./api');
      await api.compareBanks([1, 2, 3], ['cet1_ratio']);
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toBe(`${BASE}/compare?certs=1%2C2%2C3&metrics=cet1_ratio`);
    });

    it('omits the metrics param entirely when none are passed', async () => {
      const { api } = await import('./api');
      await api.compareBanks([7]);
      const url = fetchMock.mock.calls[0][0] as string;
      expect(url).toBe(`${BASE}/compare?certs=7`);
    });
  });

  describe('error unwrapping', () => {
    it('rejects with the JSON body\'s error message on a non-2xx response', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ error: 'deposit-flight model not trained yet' }, { ok: false, status: 409, statusText: 'Conflict' }),
      );
      const { api } = await import('./api');
      await expect(api.health()).rejects.toThrow('deposit-flight model not trained yet');
    });

    it('falls back to "<status> <statusText>" when the error body is not valid JSON', async () => {
      fetchMock.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: () => Promise.reject(new Error('not json')),
      } as Response);
      const { api } = await import('./api');
      await expect(api.health()).rejects.toThrow('500 Internal Server Error');
    });

    it('resolves with the parsed JSON body on a 2xx response', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }));
      const { api } = await import('./api');
      await expect(api.health()).resolves.toEqual({ status: 'ok' });
    });
  });

  describe('Authorization header attachment', () => {
    it('omits the Authorization header when there is no signed-in user', async () => {
      getCurrentUser.mockResolvedValue(null);
      const { api } = await import('./api');
      await api.health();
      const init = fetchMock.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
    });

    it('omits the Authorization header when the user has no access_token', async () => {
      getCurrentUser.mockResolvedValue({ access_token: '' });
      const { api } = await import('./api');
      await api.health();
      const init = fetchMock.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
    });

    it('attaches "Bearer <access_token>" when a token is available', async () => {
      getCurrentUser.mockResolvedValue({ access_token: 'tok-abc123' });
      const { api } = await import('./api');
      await api.health();
      const init = fetchMock.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-abc123');
    });

    it('attaches the same header on a POST alongside Content-Type', async () => {
      getCurrentUser.mockResolvedValue({ access_token: 'tok-post' });
      fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
      const { api } = await import('./api');
      await api.addToWatchlist(123);
      const init = fetchMock.mock.calls[0][1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers.Authorization).toBe('Bearer tok-post');
      expect(headers['Content-Type']).toBe('application/json');
      expect(init.method).toBe('POST');
      expect(init.body).toBe(JSON.stringify({ cert: 123 }));
    });
  });
});

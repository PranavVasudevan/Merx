import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const getCurrentUser = vi.fn();
vi.mock('./auth', () => ({ getCurrentUser: () => getCurrentUser() }));

// BASE falls back to the local dev bridge (see api.ts) since VITE_API_BASE
// isn't set for the test run.
const BASE = 'http://localhost:8791/api';

function jsonResponse(
  body: unknown,
  init: { ok?: boolean; status?: number; statusText?: string; etag?: string | null } = {},
) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? 'OK',
    json: () => Promise.resolve(body),
    // F10 — get()'s conditional-GET path reads the ETag response header
    // (via CORS-exposed Access-Control-Expose-Headers on the real bridge);
    // `null` here is the realistic default for a route with no ETag.
    headers: { get: (name: string) => (name.toLowerCase() === 'etag' ? (init.etag ?? null) : null) },
  } as unknown as Response;
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

    it('appends the request_id to the thrown message when the bridge included one (F17)', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ error: 'missing required param: cert', request_id: 'abc123def456' },
                     { ok: false, status: 400, statusText: 'Bad Request' }),
      );
      const { api } = await import('./api');
      await expect(api.health()).rejects.toThrow('missing required param: cert (request: abc123def456)');
    });

    it('omits the "(request: ...)" suffix entirely when no request_id is present', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ error: 'plain error, no id' }, { ok: false, status: 400, statusText: 'Bad Request' }),
      );
      const { api } = await import('./api');
      await expect(api.health()).rejects.toThrow('plain error, no id');
      await expect(api.health()).rejects.not.toThrow(/request:/);
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

  // F10 — client side of the bridge's ETag/304 contract (bridge_server.py's
  // _prepare_json_body). No fetch mock resets `_etagCache` between calls, so
  // these tests exercise the SAME in-memory cache across calls on purpose.
  describe('conditional GET (ETag) caching', () => {
    it('sends no If-None-Match on the first request for a URL', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }, { etag: '"abc"' }));
      const { api } = await import('./api');
      await api.health();
      const init = fetchMock.mock.calls[0][1] as RequestInit;
      expect((init.headers as Record<string, string>)['If-None-Match']).toBeUndefined();
    });

    it('sends the remembered ETag as If-None-Match on a repeat request to the same URL', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ status: 'ok' }, { etag: '"cache-key-1"' }));
      const { api } = await import('./api');
      await api.health();
      await api.health();
      const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
      expect((secondInit.headers as Record<string, string>)['If-None-Match']).toBe('"cache-key-1"');
    });

    it('returns the previously-cached body on a 304, without a real body in the response', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ status: 'ok' }, { etag: '"cache-key-2"' }));
      const { api } = await import('./api');
      const first = await api.health();

      fetchMock.mockResolvedValueOnce({
        ok: false, status: 304, statusText: 'Not Modified',
        json: () => Promise.reject(new Error('304 has no body')),
        headers: { get: () => null },
      } as unknown as Response);
      const second = await api.health();
      expect(second).toEqual(first);
    });

    it('does not cache a response with no ETag (repeat request still sends no If-None-Match)', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
      const { api } = await import('./api');
      await api.health();
      await api.health();
      const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
      expect((secondInit.headers as Record<string, string>)['If-None-Match']).toBeUndefined();
    });
  });
});

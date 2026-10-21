import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, setCsrfToken } from "./api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

const fetchMock = vi.fn();

afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  setCsrfToken("");
});

describe("api client", () => {
  it("keeps Accept on GET and sends no CSRF header", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));

    await api.get("/api/auth/config");

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBeUndefined();
    expect(init.headers).toMatchObject({ Accept: "application/json" });
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(init.credentials).toBe("same-origin");
  });

  it("sends the in-memory CSRF token on POST and preserves content type", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    setCsrfToken("token-one");

    await api.post("/api/auth/login", { password: "x" });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toMatchObject({
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": "token-one"
    });
    expect(init.body).toBe('{"password":"x"}');
  });

  it("uses the rotated token and drops it on clear", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    setCsrfToken("first");
    await api.post("/api/auth/logout");
    setCsrfToken("second");
    await api.post("/api/auth/logout");
    setCsrfToken("");
    await api.post("/api/auth/logout");

    const headers = fetchMock.mock.calls.map(
      (call) => (call[1] as RequestInit).headers as Record<string, string>
    );
    expect(headers[0]["X-CSRF-Token"]).toBe("first");
    expect(headers[1]["X-CSRF-Token"]).toBe("second");
    expect(headers[2]["X-CSRF-Token"]).toBeUndefined();
  });

  it("surfaces the API detail without losing the status", async () => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockResolvedValue(jsonResponse({ detail: "csrf token missing or invalid" }, 403));

    await expect(api.post("/api/goals/preview", {})).rejects.toMatchObject({
      name: "ApiError",
      status: 403,
      message: "csrf token missing or invalid"
    } satisfies Partial<ApiError>);
  });
});

import { describe, expect, it } from "vitest";
import { requireAuth } from "../src/auth";

const env = { AUTH_TOKEN: "secret-token" } as { AUTH_TOKEN: string };

describe("requireAuth", () => {
  it("returns null when the Authorization header matches", () => {
    const request = new Request("https://example.com/", {
      headers: { Authorization: "Bearer secret-token" },
    });

    expect(requireAuth(request, env)).toBeNull();
  });

  it("returns 401 when the Authorization header is missing", () => {
    const request = new Request("https://example.com/");

    const response = requireAuth(request, env);

    expect(response).not.toBeNull();
    expect(response?.status).toBe(401);
  });

  it("returns 401 when the Authorization header has the wrong token", () => {
    const request = new Request("https://example.com/", {
      headers: { Authorization: "Bearer wrong-token" },
    });

    const response = requireAuth(request, env);

    expect(response).not.toBeNull();
    expect(response?.status).toBe(401);
  });

  it("returns 401 when AUTH_TOKEN is unset", () => {
    const unsetEnv = { AUTH_TOKEN: "" } as { AUTH_TOKEN: string };
    const request = new Request("https://example.com/", {
      headers: { Authorization: "Bearer undefined" },
    });

    const response = requireAuth(request, unsetEnv);

    expect(response).not.toBeNull();
    expect(response?.status).toBe(401);
  });
});

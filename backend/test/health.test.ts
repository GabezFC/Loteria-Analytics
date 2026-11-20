import { describe, expect, it, vi } from "vitest";
import { buildApp, type Db } from "../src/app.js";

const okDb: Db = { query: vi.fn(async () => ({ rows: [{ "?column?": 1 }] })) };

describe("health", () => {
  for (const url of ["/health", "/api/health"]) {
    it(`${url} retorna ok com banco disponível`, async () => {
      const app = buildApp({ db: okDb });
      const res = await app.inject({ method: "GET", url });
      expect(res.statusCode).toBe(200);
      expect(res.json()).toEqual({ status: "ok", database: "up" });
      expect(okDb.query).toHaveBeenCalledWith("SELECT 1");
      await app.close();
    });

    it(`${url} retorna 503 sanitizado quando o banco falha`, async () => {
      const db: Db = {
        query: async () => {
          throw new Error("password authentication failed for user cassino_api at 10.0.0.5");
        },
      };
      const app = buildApp({ db });
      const res = await app.inject({ method: "GET", url });
      expect(res.statusCode).toBe(503);
      expect(res.json()).toEqual({ status: "degraded", database: "down" });
      expect(res.body).not.toMatch(/password|cassino_api|10\.0\.0\.5/);
      await app.close();
    });
  }

  it("retorna 503 em timeout do banco", async () => {
    const db: Db = { query: () => new Promise(() => {}) };
    const app = buildApp({ db, dbTimeoutMs: 20 });
    const res = await app.inject({ method: "GET", url: "/health" });
    expect(res.statusCode).toBe(503);
    expect(res.json().status).toBe("degraded");
    await app.close();
  });

  it("as duas rotas devolvem a mesma resposta", async () => {
    const app = buildApp({ db: okDb });
    const a = await app.inject({ method: "GET", url: "/health" });
    const b = await app.inject({ method: "GET", url: "/api/health" });
    expect(a.statusCode).toBe(b.statusCode);
    expect(a.body).toBe(b.body);
    await app.close();
  });
});

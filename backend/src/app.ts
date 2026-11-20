import Fastify, { type FastifyInstance } from "fastify";

/** Contrato mínimo do pool: facilita injeção de dublê nos testes. */
export interface Db {
  query(text: string): Promise<unknown>;
}

export interface HealthBody {
  status: "ok" | "degraded";
  database: "up" | "down";
}

export interface BuildOptions {
  db: Db;
  logger?: boolean;
  /** Tempo máximo (ms) para o SELECT 1. */
  dbTimeoutMs?: number;
}

export function buildApp({ db, logger = false, dbTimeoutMs = 3000 }: BuildOptions): FastifyInstance {
  const app = Fastify({ logger });

  async function checkHealth(): Promise<{ code: 200 | 503; body: HealthBody }> {
    let timer: NodeJS.Timeout | undefined;
    try {
      await Promise.race([
        db.query("SELECT 1"),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("timeout")), dbTimeoutMs);
        }),
      ]);
      return { code: 200, body: { status: "ok", database: "up" } };
    } catch (err) {
      // Detalhes só no log do servidor; a resposta é sanitizada.
      app.log.error({ err }, "health check: banco indisponível");
      return { code: 503, body: { status: "degraded", database: "down" } };
    } finally {
      clearTimeout(timer);
    }
  }

  const handler = async (_req: unknown, reply: { code(c: number): unknown }) => {
    const { code, body } = await checkHealth();
    reply.code(code);
    return body;
  };

  app.get("/health", handler);
  app.get("/api/health", handler);

  return app;
}

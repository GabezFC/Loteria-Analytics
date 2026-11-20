import pg from "pg";
import { buildApp } from "./app.js";
import { registerDrawRoutes } from "./draws.js";
import { registerExperimentRoutes } from "./experiments.js";
import { registerOpsRoutes, registerProbabilityRoutes, registerStatsRoutes } from "./api.js";

// pg lê PGHOST, PGPORT, PGDATABASE, PGUSER e PGPASSWORD do ambiente.
const pool = new pg.Pool({
  max: 5,
  connectionTimeoutMillis: 3000,
  statement_timeout: 3000,
});
// Evita derrubar o processo por erro em conexão ociosa.
pool.on("error", (err) => app.log.error({ err }, "erro em conexão ociosa do pool"));

const app = buildApp({ db: pool, logger: true });
await registerDrawRoutes(app, pool);
await registerOpsRoutes(app, pool);
await registerProbabilityRoutes(app, pool);
await registerStatsRoutes(app, pool);
await registerExperimentRoutes(app, pool);

let closing = false;
async function shutdown(signal: string): Promise<void> {
  if (closing) return;
  closing = true;
  app.log.info({ signal }, "encerrando");
  const force = setTimeout(() => process.exit(1), 10_000);
  force.unref();
  try {
    await app.close();
    await pool.end();
    process.exit(0);
  } catch (err) {
    app.log.error({ err }, "falha no encerramento");
    process.exit(1);
  }
}
process.on("SIGTERM", () => void shutdown("SIGTERM"));
process.on("SIGINT", () => void shutdown("SIGINT"));

try {
  await app.listen({ host: "0.0.0.0", port: 3001 });
} catch (err) {
  app.log.error({ err }, "falha ao iniciar");
  process.exit(1);
}

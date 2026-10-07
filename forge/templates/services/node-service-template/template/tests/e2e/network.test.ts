import { expect, it } from "vitest";
import { buildApp } from "../../src/app.js";

it("serves real HTTP through the application middleware and router", async () => {
  const app = await buildApp();
  try {
    const address = await app.listen({ host: "127.0.0.1", port: 0 });
    const response = await fetch(address + "/api/v1/health/live");
    expect(response.status).toBe(200);
    expect((await response.json()).status).toBe("UP");
    expect((await fetch(address + "/not-found")).status).toBe(404);
  } finally {
    await app.close();
  }
});

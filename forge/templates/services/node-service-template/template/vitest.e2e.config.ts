import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: ["tests/e2e/**/*.test.ts"],
    env: { NODE_ENV: "testing" },
    passWithNoTests: false,
    coverage: { provider: "v8", include: ["src/**/*.ts", "../../packages/*/src/**/*.ts", "packages/*/src/**/*.ts"], allowExternal: true, exclude: ["**/*.test.ts", "**/*.d.ts"], reporter: ["json", "lcov", "text"] },
  },
});

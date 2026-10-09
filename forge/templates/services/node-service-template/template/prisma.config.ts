import "dotenv/config";
import { defineConfig } from "prisma/config";

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: { path: "prisma/migrations" },
  // Generation does not connect. Database commands require DATABASE_URL.
  datasource: { url: process.env.DATABASE_URL },
});

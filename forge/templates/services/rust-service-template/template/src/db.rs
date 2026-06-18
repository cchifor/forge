use sqlx::PgPool;
use sqlx::postgres::PgPoolOptions;

pub async fn create_pool() -> PgPool {
    let url = std::env::var("DATABASE_URL").expect("DATABASE_URL must be set");
    // Lazy pool: validate the URL but do NOT open a connection at boot. The
    // first query connects, so an unreachable database at startup does not panic
    // the process into CrashLoopBackOff — matching Python's lazy engine and
    // Node's lazy PrismaClient. /health/ready (sqlx "SELECT 1") surfaces a
    // DB-down as 503 and the pod self-heals once Postgres is reachable. (audit #24)
    PgPoolOptions::new()
        .max_connections(10)
        .connect_lazy(&url)
        .expect("invalid DATABASE_URL")
}

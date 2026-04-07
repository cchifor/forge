pub struct Config {
    pub port: u16,
    pub database_url: String,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            port: std::env::var("PORT")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(5000),
            database_url: std::env::var("DATABASE_URL")
                .expect("DATABASE_URL must be set"),
        }
    }
}

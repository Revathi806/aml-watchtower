from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = ""
    jwt_secret: str = "development-only-change-me"
    demo_analyst_email: str = "analyst@example.com"
    demo_analyst_password: str = "ChangeMe123!"
    demo_admin_email: str = "admin@example.com"
    demo_admin_password: str = "ChangeMe123!"
    kafka_bootstrap_servers: str = "localhost:9092"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:3000"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

settings = Settings()

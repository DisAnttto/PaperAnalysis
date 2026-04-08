from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"

    # NCBI / PubMed
    NCBI_API_KEY: str = ""
    NCBI_EMAIL: str = ""

    # Database
    DATABASE_URL: str = "sqlite:///./data/medlit.db"

    # App
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"


settings = Settings()

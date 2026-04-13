from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Tuple, Type

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# Resolve .env relative to this file so it always loads correctly
# regardless of where uvicorn is launched from.
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    # LLM (OpenAI-compatible client: DashScope, OpenRouter, OpenAI, NVIDIA NIM, etc.)
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "qwen-plus"
    LLM_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # When "nvidia_nim", use NVIDIA_NIM_* for api_key/base_url/model (Kimi on NIM, etc.)
    LLM_BACKEND: Literal["default", "nvidia_nim"] = "default"
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_NIM_MODEL: str = "moonshotai/kimi-k2.5"
    # Optional fast/cheap model for mechanical tasks (falls back to main when unset)
    LLM_LIGHT_MODEL: str = ""
    LLM_LIGHT_BASE_URL: str = ""
    LLM_LIGHT_API_KEY: str = ""

    # NCBI / PubMed
    NCBI_API_KEY: str = ""
    NCBI_EMAIL: str = ""

    # External API clients for correlated-evidence retrieval
    OPENFDA_API_KEY: str = ""
    OPENFDA_BASE_URL: str = "https://api.fda.gov"
    CLINICALTRIALS_BASE_URL: str = "https://clinicaltrials.gov/api/v2"
    ACCESSGUDID_BASE_URL: str = "https://accessgudid.nlm.nih.gov/api/v2"
    DAILYMED_BASE_URL: str = "https://dailymed.nlm.nih.gov/dailymed/services/v2"

    # Database
    DATABASE_URL: str = "sqlite:///./data/medlit.db"

    # App — env file takes priority over system env vars so a stale
    # APP_MODE=demo process-level variable cannot override the .env value.
    APP_ENV: str = "development"
    APP_MODE: str = "dev"
    LOG_LEVEL: str = "INFO"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        **kwargs: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # .env file > system env vars > defaults
        # This prevents a stale system APP_MODE env var from overriding .env
        ordered = [
            kwargs.get("init_settings"),
            kwargs.get("dotenv_settings"),
            kwargs.get("env_settings"),
            kwargs.get("file_secret_settings") or kwargs.get("secrets_dir_settings"),
        ]
        return tuple(s for s in ordered if s is not None)


@dataclass(frozen=True)
class LLMClientConfig:
    """Resolved credentials for AsyncOpenAI (and compatible SDKs)."""

    api_key: str
    base_url: str | None
    model: str
    backend: Literal["default", "nvidia_nim"]


def get_llm_client_config() -> LLMClientConfig:
    """Return active LLM endpoint: default env vars or NVIDIA NIM (Kimi)."""
    s = settings
    if s.LLM_BACKEND == "nvidia_nim" and (s.NVIDIA_NIM_API_KEY or "").strip():
        base = (s.NVIDIA_NIM_BASE_URL or "").strip() or "https://integrate.api.nvidia.com/v1"
        model = (s.NVIDIA_NIM_MODEL or "").strip() or s.LLM_MODEL
        return LLMClientConfig(
            api_key=s.NVIDIA_NIM_API_KEY.strip(),
            base_url=base,
            model=model,
            backend="nvidia_nim",
        )
    bu = (s.LLM_BASE_URL or "").strip() or None
    return LLMClientConfig(
        api_key=s.LLM_API_KEY,
        base_url=bu,
        model=s.LLM_MODEL,
        backend="default",
    )


def get_llm_light_config() -> LLMClientConfig:
    """Light-tier model for mechanical tasks. Falls back to main model when unset."""
    s = settings
    if not (s.LLM_LIGHT_MODEL or "").strip():
        return get_llm_client_config()
    return LLMClientConfig(
        api_key=(s.LLM_LIGHT_API_KEY or s.LLM_API_KEY).strip(),
        base_url=(s.LLM_LIGHT_BASE_URL or s.LLM_BASE_URL or "").strip() or None,
        model=s.LLM_LIGHT_MODEL.strip(),
        backend=s.LLM_BACKEND,
    )


def llm_is_configured() -> bool:
    return bool(get_llm_client_config().api_key)


def get_llm_extra_request_kwargs() -> dict:
    """Extra args for chat.completions.create (OpenAI SDK + compatible providers).

    NVIDIA Kimi K2.5 defaults to thinking mode, which returns empty ``content`` and
    fills ``reasoning`` instead — extraction/triage/relevance expect ``content``.
    """
    if get_llm_client_config().backend == "nvidia_nim":
        return {"extra_body": {"chat_template_kwargs": {"thinking": False}}}
    return {}


settings = Settings()

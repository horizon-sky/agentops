"""全局配置：所有外部依赖均通过环境变量注入，代码不写死任何密钥。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_env: str = "dev"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"
    api_token: str = ""
    web_origin: str = "http://localhost:3000"
    resend_api_key: str = ""
    mail_from: str = ""
    auth_session_hours: int = 1
    max_active_runs_per_user: int = 2
    max_runs_per_user_per_day: int = 50
    max_ingests_per_user_per_day: int = 20

    # ---- 数据层 ----
    database_url: str = ""
    redis_url: str = ""

    # ---- 模型（OpenAI 兼容协议）----
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_model_cheap: str = ""
    llm_model_strong: str = ""
    request_timeout_s: float = 60.0

    # ---- Embedding ----
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # ---- Rerank ----
    rerank_enabled: bool = False
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = "bge-reranker-v2-m3"

    # ---- 可观测 ----
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ---- 运行时开关 ----
    mcp_mode: str = "inprocess"  # inprocess | stdio
    agent_mode: str = "echo"  # echo（链路跑通） | graph（LangGraph 编排，M2 启用）
    prompt_version: str = "2026.09.22-v1"

    @property
    def cors_origins_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def cheap_model(self) -> str:
        return self.llm_model_cheap or self.llm_model

    @property
    def strong_model(self) -> str:
        return self.llm_model_strong or self.llm_model

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url)

    @property
    def has_embedding(self) -> bool:
        return bool(self.embedding_api_key and self.embedding_base_url)

    @property
    def has_database(self) -> bool:
        return bool(self.database_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

"""Application settings loaded from environment variables or a local .env file."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the KHIND sales agent."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GCP / Vertex AI
    google_cloud_project: str = "prudential-poc-484904"
    google_cloud_location: str = "asia-southeast1"
    llm_model: str = "gemini-2.5-flash"
    vertex_rag_corpus: str = Field(
        default=(
            "projects/prudential-poc-484904/locations/asia-southeast1/"
            "ragCorpora/2305843009213693952"
        ),
        alias="RAG_CORPUS_NAME",
    )

    # Session store: the Agent Engine resource ID. Empty keeps sessions in process memory
    # (local runs only: lost on restart and not shared between instances).
    vertex_ai_agent_engine_id: str = Field(default="", alias="VERTEX_AI_AGENT_ENGINE_ID")

    # Google Cloud Storage
    gcs_bucket: str = Field(default="khind_2028", alias="GCS_BUCKET")

    # Chatwoot — set all three in .env for outbound delivery and escalation to work
    chatwoot_base_url: str = Field(default="", alias="CHATWOOT_BASE_URL")
    chatwoot_api_token: str = Field(default="", alias="CHATWOOT_API_TOKEN")
    chatwoot_account_id: str = Field(default="", alias="CHATWOOT_ACCOUNT_ID")
    # The agent bot's "Webhook Secret" (Chatwoot > Settings > Bots). Chatwoot signs each
    # webhook call with it; without it every call is rejected.
    chatwoot_webhook_secret: str = Field(default="", alias="CHATWOOT_WEBHOOK_SECRET")
    # Escalation assignment — set one of these (agent preferred over team):
    # CHATWOOT_HUMAN_AGENT_ID  — individual agent ID (use when no teams, single-agent setup)
    # CHATWOOT_HUMAN_TEAM_ID   — team ID (use when Chatwoot teams are configured)
    chatwoot_human_agent_id: str = Field(default="", alias="CHATWOOT_HUMAN_AGENT_ID")
    chatwoot_human_team_id: str = Field(default="", alias="CHATWOOT_HUMAN_TEAM_ID")

    # Server
    port: int = Field(default=8081, alias="PORT")


settings = Settings()
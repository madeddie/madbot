from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    telegram_bot_token: str
    opencode_api_key: str

    ai_provider: str = "opencodego"
    ai_model: str = "glm-5.1"

    system_prompt: str = "You are a helpful assistant."
    max_history_messages: int = Field(default=20, ge=1, le=200)
    db_path: str = Field(default="madbot.db")
    debug: bool = Field(default=False)

    owner_chat_id: int = Field(default=0)

    amazon_username: str = ""
    amazon_password: str = ""
    amazon_otp_secret: str = ""


settings = Settings()

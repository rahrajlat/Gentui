"""Settings loaded from environment variables / a local .env file."""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Export .env into os.environ. Strands harness reads provider credentials
# (OLLAMA_HOST, OPENAI_API_KEY, AWS_*, ...) from there, not from our Settings.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GENTUI_", extra="ignore")

    # "<provider>/<model>", resolved by the Strands harness. Any provider it supports.
    model: str = "ollama/gpt-oss:120b-cloud"
    effort: str = "auto"

    # Shell execution limits
    shell_cwd: str = "."  # working directory for approved commands
    shell_timeout: int = 30  # seconds
    shell_max_output: int = 8000  # characters kept from stdout+stderr


def get_settings() -> Settings:
    return Settings()

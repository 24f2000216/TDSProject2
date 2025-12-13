# config.py
"""
Configuration management using Pydantic Settings.
Loads environment variables from .env file in the same directory.
"""

from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Application configuration."""
    
    # API Configuration
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    
    # Authentication (REQUIRED)
    SECRET_KEY: str
    ALLOWED_EMAIL: str
    
    # LLM Configuration (REQUIRED)
    LLM_API_KEY: str
    LLM_BASE_URL: str
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: int = 150
    
    # Scraper Configuration
    BROWSER_TIMEOUT_MS: int = 30000
    PAGE_LOAD_TIMEOUT_SECONDS: int = 30
    RESOURCE_FETCH_TIMEOUT_SECONDS: int = 30
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_SECONDS: float = 1.0
    
    # Orchestration
    MAX_ITERATIONS: int = 10
    MAX_TIME_PER_QUESTION_SECONDS: int = 300
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

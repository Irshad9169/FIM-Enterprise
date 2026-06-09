"""
Configuration Management
"""
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    # Application
    app_name: str = "Enterprise FIM Server"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Database
    database_url: str
    
    # Security
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    
    # CORS
    cors_origins: List[str] = ["*"]
    
    # SMTP (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    
    class Config:
        env_file = "/opt/fim/.env"
        case_sensitive = False

settings = Settings()

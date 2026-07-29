"""
Configuration Management
"""
import os
from pydantic_settings import BaseSettings
from typing import List, Dict, Tuple, Set, Optional, List

FIM_HOME = os.environ.get("FIM_HOME", "/opt/fim")

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

    # Ticket-system integrations (RT / CMR / JIRA) — previously hardcoded
    # module constants in ticket_linker.py; defaults below match those
    # original values so behavior is unchanged unless overridden via .env.
    rt_lookup_url: str = "http://rtapi.int.untd.com/cgi-bin/rt.cgi"
    rt_update_url: str = "https://rtapi.int.untd.com/cgi-bin/rt.cgi"
    rt_email: str = "security@tickets.int.untd.com"
    cmr_url: str = "https://phantom.int.untd.com/bin/phantom"

    # JIRA is net-new (previously unimplemented). jira_url empty disables it.
    # Auth: set jira_email + jira_api_token for Basic auth (JIRA Cloud-style),
    # or jira_api_token alone for Bearer auth (JIRA Server/Data Center PAT) —
    # confirm which one matches your actual JIRA instance before enabling.
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""

    class Config:
        env_file = f"{FIM_HOME}/.env"
        case_sensitive = False

settings = Settings()

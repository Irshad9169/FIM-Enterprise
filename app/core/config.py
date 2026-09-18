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
    # 8h, matching app/core/security.py's long-standing hardened default
    # (its docstring: "Default expiry reduced to 8 hours") — this field
    # was previously unused (security.py read its own os.getenv() with
    # this exact same fallback value), so this isn't a behavior change.
    access_token_expire_minutes: int = 480
    
    # CORS — dev-server origins by default; production MUST override via
    # .env (a wildcard here would be pointless anyway once combined with
    # allow_credentials=True in app/main.py, which browsers reject outright).
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
    
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

    # SSO login redirect target — was hardcoded in app/core/sso_manager.py
    # (previously the QA endpoint, auth.qa.int.untd.com) with .env.example's
    # SSO_SERVER_URL documented but never actually read. Default below is
    # the production endpoint.
    sso_server_url: str = "https://auth.int.untd.com/bin/sso"

    # CMR (Phantom) has no dedicated API -- only its own web UI behind
    # company SSO. This points at a Netscape-format cookie jar file that
    # holds a valid Phantom session; FIM reuses whatever's currently there.
    # Empty = CMR fetch on the Reports page is skipped entirely, not an
    # error. Populated by app/services/cmr_session_manager.py's on-demand
    # login (see below) -- triggered from the Correlate All button when
    # there's no valid session yet, using the analyst's own SSO
    # username/password entered at that moment. Same mechanism the legacy
    # get_RT_CMRs collector uses (confirmed from its real source): there is
    # no service-account concept here, just whatever real credential gets
    # submitted, exactly like the legacy system.
    cmr_cookie_jar_path: str = ""

    # Params for the SSO type=login call app/services/cmr_session_manager.py
    # makes -- everything except the username/password itself, which is
    # never stored anywhere and is supplied per-request instead. UNVERIFIED:
    # the legacy collector proves this login mode works using its own
    # already-registered SSO origin (origin_id "USTickets"); whether the
    # SSO server accepts a different origin_id (FIM's own, below) for this
    # same mode has not been tested. If rejected, the legacy system's exact
    # origin values are the known-working fallback to try.
    cmr_sso_origin_name: str = "FIM Enterprise"
    cmr_sso_origin_id: str = "FIM_ENTERPRISE"
    cmr_sso_origin_url: str = ""

    # Daily report auto-generation (app/services/report_scheduler.py) —
    # previously its own os.getenv() calls, same fragility as SECRET_KEY
    # above (silently falls back if EnvironmentFile= isn't wired into the
    # systemd unit), just lower-stakes since it's a schedule, not a secret.
    report_auto_generate: bool = True
    report_schedule_hour: int = 9      # 0-23, IST
    report_schedule_minute: int = 0    # 0-59

    class Config:
        env_file = f"{FIM_HOME}/.env"
        case_sensitive = False

settings = Settings()

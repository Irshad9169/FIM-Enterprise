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
    # something keeps a valid Phantom session in; FIM reuses whatever
    # session is currently there. Empty = CMR fetch on the Reports page is
    # skipped entirely, not an error. That "something" can be either:
    #   (a) a file manually refreshed by an external process/person, or
    #   (b) app/services/cmr_session_manager.py, if cmr_sso_username/
    #       cmr_sso_password below are set -- it logs in on a schedule and
    #       writes this same file itself.
    cmr_cookie_jar_path: str = ""

    # CMR (Phantom) auto-login -- mirrors the legacy get_RT_CMRs collector's
    # own mechanism (confirmed from its actual source): a direct
    # username+password call to the SSO server's `type=login` mode, then
    # presenting the resulting cookie to Phantom's front door to receive a
    # Phantom session cookie -- automated on a schedule here instead of
    # tied to a human logging into a web form the way the legacy system is.
    # Empty username/password = this feature is disabled; cmr_cookie_jar_path
    # above is then whatever it already was (unmanaged/manually refreshed).
    # UNVERIFIED end-to-end: the legacy collector proves this mechanism
    # works using its own already-registered SSO origin (origin_id
    # "USTickets"); whether the SSO server accepts a different origin_id
    # for this same type=login mode has not been tested. If FIM's own
    # origin_id below is rejected, the legacy system's exact origin values
    # are the known-working fallback to try.
    cmr_sso_username: str = ""
    cmr_sso_password: str = ""
    cmr_sso_origin_name: str = "FIM Enterprise"
    cmr_sso_origin_id: str = "FIM_ENTERPRISE"
    cmr_sso_origin_url: str = ""
    cmr_session_refresh_minutes: int = 60

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

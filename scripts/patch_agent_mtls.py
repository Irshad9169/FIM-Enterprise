#!/usr/bin/env python3
"""
Patch fim_agent.py to add mTLS client certificate support.
Run: python3 /opt/fim/patch_agent_mtls.py
"""

AGENT_PATH = "/opt/fim/agent/fim_agent.py"

with open(AGENT_PATH) as f:
    code = f.read()

# ── 1. Replace FIMClient.__init__ to accept TLS config ────────────────────

old_init = '''class FIMClient:
    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json'
        })
        self.logger = logging.getLogger('FIMAgent.Client')'''

new_init = '''class FIMClient:
    def __init__(self, server_url: str, api_key: str, tls_config: dict = None):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json'
        })
        self.logger = logging.getLogger('FIMAgent.Client')

        # ── mTLS Configuration ────────────────────────────────────────
        # When TLS is enabled, the agent presents its client certificate
        # to the server for mutual authentication. The server (nginx)
        # verifies the cert was signed by the FIM CA.
        #
        # Config format in agent_config.yaml:
        #   tls:
        #     enabled: true
        #     ca_cert: certs/ca.crt          # CA cert to verify server
        #     client_cert: certs/agent.crt   # Agent's certificate
        #     client_key: certs/agent.key    # Agent's private key
        #     verify_server: true            # Verify server cert (default: true)
        #
        if tls_config and tls_config.get('enabled'):
            client_cert = tls_config.get('client_cert')
            client_key = tls_config.get('client_key')
            ca_cert = tls_config.get('ca_cert')
            verify_server = tls_config.get('verify_server', True)

            if client_cert and client_key:
                self.session.cert = (client_cert, client_key)
                self.logger.info(f"mTLS enabled: cert={client_cert}")
            else:
                self.logger.warning("TLS enabled but client_cert/client_key not set")

            if ca_cert and verify_server:
                self.session.verify = ca_cert
                self.logger.info(f"Server verification: ca={ca_cert}")
            elif not verify_server:
                self.session.verify = False
                self.logger.warning("Server certificate verification DISABLED")
        else:
            self.logger.info("TLS not configured — using plain HTTP")'''

if old_init in code:
    code = code.replace(old_init, new_init)
    print("  Patched FIMClient.__init__ with mTLS support")
else:
    print("  WARNING: Could not find FIMClient.__init__ — check manually")

# ── 2. Update FIMAgent.__init__ to pass TLS config to FIMClient ───────────

old_client = '''        self.client = FIMClient(
            self.config['server']['url'],
            self.config['server']['api_key']
        )'''

new_client = '''        # Load TLS configuration (optional)
        tls_config = self.config.get('tls', {})
        if tls_config.get('enabled'):
            # Resolve cert paths relative to agent directory
            agent_dir = os.path.dirname(os.path.abspath(config_file))
            for key in ('ca_cert', 'client_cert', 'client_key'):
                path = tls_config.get(key, '')
                if path and not os.path.isabs(path):
                    tls_config[key] = os.path.join(agent_dir, path)

        self.client = FIMClient(
            self.config['server']['url'],
            self.config['server']['api_key'],
            tls_config=tls_config
        )'''

if old_client in code:
    code = code.replace(old_client, new_client)
    print("  Patched FIMAgent.__init__ to pass TLS config")
else:
    print("  WARNING: Could not find FIMClient instantiation — check manually")

with open(AGENT_PATH, 'w') as f:
    f.write(code)

print("\nDone! Agent now supports mTLS when configured.")
print("\nUpdate agent_config.yaml:")
print("  server:")
print("    url: https://<server-hostname>")
print("  tls:")
print("    enabled: true")
print("    ca_cert: certs/ca.crt")
print("    client_cert: certs/agent.crt")
print("    client_key: certs/agent.key")
print("    verify_server: true")

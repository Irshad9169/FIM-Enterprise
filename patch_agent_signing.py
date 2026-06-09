#!/usr/bin/env python3
"""
Patch fim_agent.py to sign scan results with HMAC-SHA256.
Run: python3 /opt/fim/patch_agent_signing.py
"""

AGENT_PATH = "/opt/fim/agent/fim_agent.py"

with open(AGENT_PATH) as f:
    code = f.read()

# ── Replace send_scan_results to add signature ────────────────────────────

old_send = '''    def send_scan_results(self, agent_id: str, scan_data: List[Dict]):
        """Send scan results to server"""
        try:
            data = {
                'agent_id': agent_id,
                'files': scan_data,
                'timestamp': datetime.utcnow().isoformat(),
                'total_files': len(scan_data)
            }
            response = self.session.post(
                f'{self.server_url}/api/v1/scans/submit',
                json=data,
                timeout=30
            )
            response.raise_for_status()
            self.logger.info(f"Scan results sent: {len(scan_data)} files")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send scan results: {e}")
            return False'''

new_send = '''    def send_scan_results(self, agent_id: str, scan_data: List[Dict]):
        """
        Send scan results to server with HMAC-SHA256 signature.
        The signature covers the entire JSON payload to prevent
        tampering in transit. Uses the API key as the shared secret.
        """
        try:
            data = {
                'agent_id': agent_id,
                'files': scan_data,
                'timestamp': datetime.utcnow().isoformat(),
                'total_files': len(scan_data)
            }

            # Sign the payload with HMAC-SHA256 using the API key
            canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
            signature = "hmac-sha256=" + hmac.new(
                self.api_key.encode('utf-8'),
                canonical.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            response = self.session.post(
                f'{self.server_url}/api/v1/scans/submit',
                json=data,
                headers={'X-Scan-Signature': signature},
                timeout=30
            )
            response.raise_for_status()
            self.logger.info(f"Scan results sent: {len(scan_data)} files (signed)")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send scan results: {e}")
            return False'''

if old_send in code:
    code = code.replace(old_send, new_send)
    print("Patched send_scan_results with HMAC signing")
else:
    print("WARNING: Could not find send_scan_results — check manually")

# ── Ensure hmac is imported ───────────────────────────────────────────────
if 'import hmac' not in code:
    code = code.replace(
        'import hashlib',
        'import hashlib\nimport hmac'
    )
    print("Added hmac import")

with open(AGENT_PATH, 'w') as f:
    f.write(code)

print("Done! Agent will now sign all scan submissions.")

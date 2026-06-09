import re

FILE_PATH = '/opt/fim/agent/fim_agent.py'

with open(FILE_PATH, 'r') as f:
    content = f.read()

# Define the new method body
new_method = """    def send_heartbeat(self, agent_id: str, hostname: str):
        \"\"\"Send heartbeat to server\"\"\"
        try:
            data = {
                'agent_id': agent_id,
                'hostname': hostname,
                'timestamp': datetime.utcnow().isoformat()
            }

            response = self.session.post(
                f'{self.server_url}/api/v1/agents/heartbeat',
                json=data,
                timeout=10
            )
            response.raise_for_status()
            
            # Check for on-demand scan
            try:
                resp_data = response.json()
                if isinstance(resp_data, dict) and resp_data.get('scan_required'):
                    self.logger.info("Received on-demand scan request from server")
                    # Run scan in separate thread/process if needed, or directly
                    self.run_scan()
            except Exception as json_err:
                self.logger.warning(f"Failed to parse heartbeat response: {json_err}")

            self.logger.debug("Heartbeat sent")
            return True

        except Exception as e:
            self.logger.error(f"Heartbeat failed: {e}")
            return False"""

# Regex to match the old method
# Matches from def send_heartbeat... until the return False inside except block
pattern = r"    def send_heartbeat\(self, agent_id: str, hostname: str\):[\s\S]*?return False"

# Replace
if re.search(pattern, content):
    new_content = re.sub(pattern, new_method, content, count=1)
    
    with open(FILE_PATH, 'w') as f:
        f.write(new_content)
    print("✅ Successfully updated send_heartbeat method")
else:
    print("❌ Could not find send_heartbeat method to replace")

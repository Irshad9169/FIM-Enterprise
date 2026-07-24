import re

FILE_PATH = '/opt/fim/agent/fim_agent.py'

with open(FILE_PATH, 'r') as f:
    content = f.read()

# Look for the registration method
# Assuming it's inside FIMClient class
# We want to make sure it returns the ID correctly

# Simple fix: make sure it returns the ID from the response 'id' field
# Or replace the method entirely if we can identify it

# Let's try to find where it logs "Agent registered:"
pattern = r"self\.logger\.info\(f'Agent registered: \{agent_id\}'\)"

if re.search(pattern, content):
    print("Found logging line. Checking logic around it...")
    
    # Check if it parses response.json()['id']
    # If not, let's just make sure the server returns what it needs
    pass
else:
    print("Could not find logging line")


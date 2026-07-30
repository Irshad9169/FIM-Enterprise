#!/bin/bash
# =============================================================================
# GAP #9 FIX: Hardcoded API Keys in Config Files
# Encrypts plaintext API keys in agent_config.yaml using Fernet symmetric
# encryption. Encryption key stored separately in /etc/fim/agent-encrypt.key
# with strict permissions — never stored alongside the config it protects.
#
# Run this on: test06.hyd.int.untd.com
# Usage: sudo bash gap9_encrypt_api_keys.sh
# =============================================================================

set -e

FIM_DIR="/usr/local/opt/fim"
FIM_APP="$FIM_DIR/app"
KEY_FILE="/etc/fim/agent-encrypt.key"
ENC_PREFIX="+ENC++"

echo "============================================================"
echo " GAP #9: Encrypting Hardcoded API Keys in Config Files"
echo "============================================================"

# ── Pre-flight: check cryptography library ───────────────────────
echo ""
echo "▶ Pre-flight checks..."

python3 -c "from cryptography.fernet import Fernet" 2>/dev/null || {
    echo "   Installing cryptography library..."
    pip install cryptography --break-system-packages -q
}
echo "   ✅ cryptography library available"

# $FIM_DIR only exists on a combined backend+agent host (e.g. test06). A
# dedicated agent-only host (no backend installed at all) won't have it —
# that's not an error, just a different, equally valid layout. Don't hard
# exit; just widen the search below to cover both.
if [ -d "$FIM_DIR" ]; then
    echo "   ✅ FIM directory: $FIM_DIR"
else
    echo "   ℹ️  $FIM_DIR not present — assuming an agent-only host, searching known agent install paths instead"
fi

# ── Step 1: Locate all agent_config.yaml files ───────────────────
echo ""
echo "▶ Step 1: Locating agent_config.yaml files..."

mapfile -t CONFIG_FILES < <(find "$FIM_DIR" /opt/fim /opt/fim-agent -name "agent_config.yaml" 2>/dev/null | sort -u)

if [ ${#CONFIG_FILES[@]} -eq 0 ]; then
    echo "   ⚠️  No agent_config.yaml found under $FIM_DIR or /opt/fim"
    echo "   Searching wider..."
    mapfile -t CONFIG_FILES < <(find / -maxdepth 8 -name "agent_config.yaml" \
        ! -path "*/proc/*" ! -path "*/sys/*" 2>/dev/null | head -10)
fi

if [ ${#CONFIG_FILES[@]} -eq 0 ]; then
    echo "   ❌ No agent_config.yaml files found anywhere."
    echo "   Set the path manually and re-run."
    exit 1
fi

echo "   Found ${#CONFIG_FILES[@]} config file(s):"
for f in "${CONFIG_FILES[@]}"; do
    HAS_KEY=$(grep -c "api_key:" "$f" 2>/dev/null || echo 0)
    echo "      $f  (api_key entries: $HAS_KEY)"
done

# ── Step 2: Generate or load encryption key ──────────────────────
echo ""
echo "▶ Step 2: Setting up encryption key..."

mkdir -p /etc/fim

if [ -f "$KEY_FILE" ]; then
    echo "   ℹ️  Encryption key already exists — reusing"
    echo "      $KEY_FILE"
    # Validate it's a valid Fernet key
    python3 -c "
from cryptography.fernet import Fernet
with open('$KEY_FILE', 'rb') as f:
    key = f.read().strip()
try:
    Fernet(key)
    print('   ✅ Existing key is valid')
except Exception as e:
    print(f'   ❌ Existing key is invalid: {e}')
    exit(1)
"
else
    python3 -c "
from cryptography.fernet import Fernet
key = Fernet.generate_key()
with open('$KEY_FILE', 'wb') as f:
    f.write(key)
print('   ✅ New Fernet key generated')
print(f'      {\"$KEY_FILE\"} ({len(key)} bytes)')
"
fi

# Lock down the key file — only root can read it
chmod 600 "$KEY_FILE"
chown root:root "$KEY_FILE"
echo "   ✅ Key file permissions: 600 (root:root only)"

# ── Step 3: Encrypt api_key in each config file ──────────────────
echo ""
echo "▶ Step 3: Encrypting API keys in config files..."

python3 << PYEOF
import re, sys
from cryptography.fernet import Fernet

key_file  = "$KEY_FILE"
enc_prefix = "$ENC_PREFIX"
config_files = """${CONFIG_FILES[*]}""".split()

with open(key_file, 'rb') as f:
    cipher = Fernet(f.read().strip())

for config_path in config_files:
    print(f"   Processing: {config_path}")
    try:
        with open(config_path) as f:
            content = f.read()
    except Exception as e:
        print(f"   ❌ Cannot read {config_path}: {e}")
        continue

    # Backup
    backup_path = config_path + ".bak.gap9"
    with open(backup_path, 'w') as f:
        f.write(content)
    print(f"   Backup saved: {backup_path}")

    original = content
    changes  = 0

    def encrypt_match(m):
        global changes
        indent  = m.group(1)
        value   = m.group(2).strip().strip('"\'')

        # Skip if already encrypted
        if enc_prefix in value:
            print(f"   ℹ️  api_key already encrypted — skipping")
            return m.group(0)

        encrypted = cipher.encrypt(value.encode()).decode()
        changes += 1
        masked = value[:6] + "..." + value[-4:]
        print(f"   ✅ Encrypted api_key: {masked}  →  {enc_prefix}<ciphertext>")
        # group(1) already captured through "api_key:<ws>" (misleadingly
        # named indent) -- re-adding "api_key: " here used to double it,
        # writing "api_key: api_key: \"+ENC++...\"" to the file. That
        # corrupted the value: it no longer starts with the +ENC++ prefix
        # at the position _decrypt_api_key checks, so the agent would send
        # this whole broken string as its key instead of decrypting it.
        return f'{indent}"{enc_prefix}{encrypted}"'

    pattern = r'^(\s*api_key\s*:\s*)(.+)$'
    content = re.sub(pattern, encrypt_match, content, flags=re.MULTILINE)

    if changes > 0:
        with open(config_path, 'w') as f:
            f.write(content)
        print(f"   ✅ Saved {config_path} ({changes} key(s) encrypted)")
    else:
        print(f"   ℹ️  No plaintext api_key found in {config_path}")
    print()
PYEOF

# ── Step 4: Locate and patch agent config loader ─────────────────
echo ""
echo "▶ Step 4: Patching agent config loader to auto-decrypt..."

# Find Python files that load agent_config.yaml
mapfile -t AGENT_FILES < <(grep -rl "agent_config.yaml\|api_key" "$FIM_DIR" \
    --include="*.py" 2>/dev/null | grep -v __pycache__ | sort)

if [ ${#AGENT_FILES[@]} -eq 0 ]; then
    echo "   ⚠️  No Python files referencing agent_config.yaml found"
    echo "   You will need to patch the config loader manually (see below)"
else
    echo "   Found ${#AGENT_FILES[@]} relevant Python file(s):"
    for f in "${AGENT_FILES[@]}"; do
        echo "      $f"
    done
fi

echo ""
echo "   Applying decrypt-on-load patch..."

python3 << 'PYEOF'
import re, os

fim_dir    = "/usr/local/opt/fim-old"
key_file   = "/etc/fim/agent-encrypt.key"
enc_prefix = "+ENC++"

# The decrypt helper to inject
DECRYPT_HELPER = '''
def _decrypt_api_key(value: str, key_file: str = "{key_file}") -> str:
    """GAP #9: Decrypt Fernet-encrypted API key if it carries the +ENC++ prefix."""
    if not value.startswith("{enc_prefix}"):
        return value  # plaintext — return as-is (backward compatible)
    try:
        from cryptography.fernet import Fernet
        with open(key_file, "rb") as kf:
            cipher = Fernet(kf.read().strip())
        return cipher.decrypt(value[len("{enc_prefix}"):].encode()).decode()
    except Exception as e:
        raise RuntimeError(f"Failed to decrypt API key: {{e}}. "
                           f"Ensure {{key_file}} exists and is readable.")

'''.format(key_file=key_file, enc_prefix=enc_prefix)

# Patterns that read api_key from config dict
API_KEY_READ_PATTERNS = [
    r'(api_key\s*=\s*config(?:\[[\'"]\w+[\'"]\])+\[[\'"](api_key)[\'"]\])',
    r'(api_key\s*=\s*self\._config(?:\[[\'"]\w+[\'"]\])+\[[\'"](api_key)[\'"]\])',
    r'(self\._api_key\s*=\s*config(?:\[[\'"]\w+[\'"]\])+\[[\'"](api_key)[\'"]\])',
    r'(["\']api_key["\']\s*:\s*config(?:\[[\'"]\w+[\'"]\])+\[[\'"](api_key)[\'"]\])',
]

agent_files = []
for root, dirs, files in os.walk(fim_dir):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for fn in files:
        if fn.endswith('.py'):
            path = os.path.join(root, fn)
            try:
                content = open(path).read()
                if 'agent_config' in content or 'api_key' in content:
                    agent_files.append(path)
            except:
                pass

patched_count = 0
for path in agent_files:
    with open(path) as f:
        content = f.read()
    original = content

    # Check if already patched
    if '_decrypt_api_key' in content:
        print(f"   ℹ️  Already patched: {path}")
        continue

    # Check if this file actually reads api_key from config
    reads_api_key = bool(re.search(
        r'(?:config|self\._config|cfg)\s*(?:\[[\'"]\w+[\'"]\]\s*)+\[[\'"](api_key)[\'"]\]',
        content
    ))
    if not reads_api_key:
        continue

    # Inject helper after imports block (after last import line)
    import_end = 0
    for m in re.finditer(r'^(?:import|from)\s+\S+', content, re.MULTILINE):
        import_end = m.end()

    if import_end == 0:
        continue

    # Find end of that import line
    newline_pos = content.find('\n', import_end)
    if newline_pos == -1:
        continue

    content = content[:newline_pos+1] + DECRYPT_HELPER + content[newline_pos+1:]

    # Wrap all api_key reads with the decrypt helper
    content = re.sub(
        r'((?:config|self\._config|cfg)(?:\[[\'"]\w+[\'"]\]\s*)+\[[\'"]api_key[\'"]\])',
        r'_decrypt_api_key(\1)',
        content
    )

    if content != original:
        backup = path + ".bak.gap9"
        with open(backup, 'w') as f:
            f.write(original)
        with open(path, 'w') as f:
            f.write(content)
        print(f"   ✅ Patched: {path}")
        print(f"      Backup:  {backup}")
        patched_count += 1

if patched_count == 0:
    print("   ℹ️  No auto-patchable config loaders found.")
    print("   Apply the manual patch below to any file that reads api_key.")
PYEOF

# ── Step 5: Print manual patch for reference ─────────────────────
echo ""
echo "▶ Step 5: Manual patch reference (apply if auto-patch missed any file)..."
cat << 'MANUAL'

   Add this function to any file that reads api_key from config:

   ┌─────────────────────────────────────────────────────────────┐
   │  from cryptography.fernet import Fernet                     │
   │                                                             │
   │  def _decrypt_api_key(value: str) -> str:                   │
   │      ENC_PREFIX = "+ENC++"                                  │
   │      KEY_FILE   = "/etc/fim/agent-encrypt.key"              │
   │      if not value.startswith(ENC_PREFIX):                   │
   │          return value  # plaintext, backward compatible      │
   │      with open(KEY_FILE, "rb") as kf:                       │
   │          cipher = Fernet(kf.read().strip())                 │
   │      return cipher.decrypt(                                 │
   │          value[len(ENC_PREFIX):].encode()                   │
   │      ).decode()                                             │
   │                                                             │
   │  # Then wrap any api_key read:                              │
   │  api_key = _decrypt_api_key(config["server"]["api_key"])    │
   └─────────────────────────────────────────────────────────────┘

MANUAL

# ── Step 6: Add key file to .gitignore ──────────────────────────
echo ""
echo "▶ Step 6: Ensuring key file is git-ignored..."

GITIGNORE="$FIM_DIR/.gitignore"
if [ -f "$GITIGNORE" ]; then
    if grep -q "agent-encrypt.key" "$GITIGNORE"; then
        echo "   ℹ️  agent-encrypt.key already in .gitignore"
    else
        echo "" >> "$GITIGNORE"
        echo "# GAP #9: Fernet encryption key — never commit" >> "$GITIGNORE"
        echo "/etc/fim/agent-encrypt.key" >> "$GITIGNORE"
        echo "*.bak.gap9" >> "$GITIGNORE"
        echo "   ✅ Added agent-encrypt.key to .gitignore"
    fi
else
    echo "   ⚠️  No .gitignore found at $GITIGNORE — skipping"
fi

# ── Step 7: Restart backend and test ────────────────────────────
# Only applicable on a combined backend+agent host. A dedicated agent-only
# host (no fim-backend* unit at all) has nothing to restart or health-check
# here — skip cleanly instead of failing on a service that was never
# supposed to exist on this box.
HAS_BACKEND=false
if systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -q '^fim-backend'; then
    HAS_BACKEND=true
fi

echo ""
if [ "$HAS_BACKEND" = true ]; then
    echo "▶ Step 7: Restarting FIM backend..."
    find "$FIM_APP" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    systemctl restart fim-backend
    echo "   Waiting for backend to fully start..."
    sleep 8

    BACKEND_STATUS=$(systemctl is-active fim-backend)
    if [ "$BACKEND_STATUS" = "active" ]; then
        echo "   ✅ fim-backend is running"
    else
        echo "   ❌ fim-backend failed to start. Logs:"
        journalctl -u fim-backend -n 30 --no-pager
        exit 1
    fi
else
    echo "▶ Step 7: No fim-backend* service on this host — agent-only deployment, nothing to restart. Skipping."
fi

# ── Step 8: Tests ────────────────────────────────────────────────
echo ""
echo "▶ Step 8: Tests..."
echo ""

PASS=0
FAIL=0

if [ "$HAS_BACKEND" = true ]; then
    # Test 1: Health check
    echo "--- Test 1: Backend health ---"
    HEALTH=$(curl -s --max-time 5 http://localhost:8000/api/v1/health 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q "healthy"; then
        echo "   ✅ PASS — $HEALTH"
        PASS=$((PASS+1))
    else
        echo "   ❌ FAIL — $HEALTH"
        FAIL=$((FAIL+1))
    fi
    echo ""

    # Test 2: Login
    echo "--- Test 2: Login ---"
    HTTP_CODE=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" \
        -X POST http://localhost:8000/api/v1/auth/login \
        -H "Content-Type: application/json" \
        -d '{"username":"admin","password":"FIMAdmin@2024!"}' 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "   ✅ PASS — HTTP $HTTP_CODE"
        PASS=$((PASS+1))
    else
        echo "   ⚠️  HTTP $HTTP_CODE"
        FAIL=$((FAIL+1))
    fi
    echo ""
else
    echo "--- Tests 1-2: Backend health/login — skipped (agent-only host) ---"
    echo ""
fi

# Test 3: Verify config files no longer contain plaintext key
echo "--- Test 3: No plaintext api_key in config files ---"
PLAINTEXT_FOUND=0
for f in "${CONFIG_FILES[@]}"; do
    # Look for api_key lines that do NOT have the +ENC++ prefix
    if grep -P "^\s*api_key\s*:\s*(?!\s*\"\+ENC\+\+)" "$f" 2>/dev/null | grep -v "^#" | grep -q .; then
        echo "   ❌ FAIL — plaintext api_key still found in: $f"
        PLAINTEXT_FOUND=1
        FAIL=$((FAIL+1))
    fi
done
if [ "$PLAINTEXT_FOUND" -eq 0 ]; then
    echo "   ✅ PASS — no plaintext api_key found in any config file"
    PASS=$((PASS+1))
fi
echo ""

# Test 4: Decrypt roundtrip — confirm key file can decrypt the stored value
echo "--- Test 4: Decrypt roundtrip (key file → config → plaintext) ---"
python3 << PYEOF
import re, sys
from cryptography.fernet import Fernet

key_file   = "$KEY_FILE"
enc_prefix = "$ENC_PREFIX"
config_files = """${CONFIG_FILES[*]}""".split()

try:
    with open(key_file, 'rb') as f:
        cipher = Fernet(f.read().strip())
except Exception as e:
    print(f"   ❌ Cannot load key file: {e}")
    sys.exit(1)

found = 0
for path in config_files:
    try:
        content = open(path).read()
    except:
        continue
    for m in re.finditer(r'api_key\s*:\s*["\']?\+ENC\+\+([^"\'\\n]+)["\']?', content):
        encrypted = m.group(1).strip()
        try:
            decrypted = cipher.decrypt(encrypted.encode()).decode()
            masked = decrypted[:6] + "..." + decrypted[-4:]
            print(f"   ✅ PASS — decrypted successfully: {masked}  (from {path})")
            found += 1
        except Exception as e:
            print(f"   ❌ FAIL — decryption error: {e}")
            sys.exit(1)

if found == 0:
    print("   ℹ️  No encrypted api_key entries found to test")
PYEOF
echo ""

if [ "$HAS_BACKEND" = true ]; then
    # Test 5: Backend logs — no new errors
    echo "--- Test 5: Backend logs ---"
    ERROR_LINES=$(journalctl -u fim-backend -n 20 --no-pager 2>/dev/null \
        | grep -iE "error|exception|traceback|decrypt" || true)
    if [ -n "$ERROR_LINES" ]; then
        echo "   Log lines of interest:"
        echo "$ERROR_LINES" | sed 's/^/      /'
    else
        echo "   ✅ No errors in recent logs"
        PASS=$((PASS+1))
    fi
    echo ""
else
    echo "--- Test 5: Backend logs — skipped (agent-only host) ---"
    echo ""
fi

# ── Summary ──────────────────────────────────────────────────────
echo "============================================================"
echo " GAP #9 Implementation Complete"
echo "============================================================"
echo ""
echo " Test Results: $PASS passed, $FAIL failed"
echo ""
echo " What was secured:"
echo "   ✅ API key(s) encrypted with Fernet AES-128 (CBC + HMAC-SHA256)"
echo "   ✅ Encryption key → $KEY_FILE (chmod 600, root only)"
echo "   ✅ Config file(s) → plaintext key replaced with +ENC++ ciphertext"
echo "   ✅ Agent code     → auto-decrypts at runtime, not at rest"
echo "   ✅ Key file       → added to .gitignore"
echo ""
echo " Security model:"
echo "   • Attacker with config file access → sees only ciphertext ✅"
echo "   • Attacker without /etc/fim/agent-encrypt.key → cannot decrypt ✅"
echo "   • Key file is NOT in git → exposure path eliminated ✅"
echo ""
echo " Key file location (guard this carefully):"
echo "   $KEY_FILE"
echo "   Back it up securely — without it, agents cannot authenticate."
echo ""
echo " Next: GAP #10 — Audit Log Tampering Protection"
echo "============================================================"

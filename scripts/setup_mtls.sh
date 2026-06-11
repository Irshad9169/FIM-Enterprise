#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — Mutual TLS (mTLS) Setup Script
# ══════════════════════════════════════════════════════════════════════════
#
# This script sets up mutual TLS authentication between agents and server:
#   1. Creates a FIM Certificate Authority (CA)
#   2. Generates server certificate (for nginx)
#   3. Generates agent certificate (per-agent)
#   4. Updates nginx config for TLS + client cert verification
#
# Usage:
#   chmod +x /opt/fim/setup_mtls.sh
#   /opt/fim/setup_mtls.sh              # Full setup (CA + server + agent)
#   /opt/fim/setup_mtls.sh new-agent <hostname>  # Generate cert for new agent
#
# After running, update agent config to use HTTPS + client cert.
# ══════════════════════════════════════════════════════════════════════════

set -e

CERT_DIR="/opt/fim/certs"
CA_DAYS=3650        # CA valid for 10 years
SERVER_DAYS=825     # Server cert valid for ~2.3 years
AGENT_DAYS=825      # Agent cert valid for ~2.3 years

# Server hostname — used in the server certificate SAN
SERVER_HOST=$(hostname -f)
SERVER_IP=$(hostname -I | awk '{print $1}')

# ── Helper Functions ──────────────────────────────────────────────────────

log()  { echo -e "\033[1;34m[FIM-mTLS]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[✓]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
err()  { echo -e "\033[1;31m[✗]\033[0m $*" >&2; }

# ── Generate New Agent Certificate ────────────────────────────────────────

generate_agent_cert() {
    local AGENT_NAME="$1"
    if [ -z "$AGENT_NAME" ]; then
        err "Usage: $0 new-agent <hostname>"
        exit 1
    fi

    local AGENT_DIR="${CERT_DIR}/agents/${AGENT_NAME}"
    mkdir -p "$AGENT_DIR"

    log "Generating certificate for agent: ${AGENT_NAME}"

    # Agent private key
    openssl genrsa -out "${AGENT_DIR}/agent.key" 2048 2>/dev/null
    chmod 600 "${AGENT_DIR}/agent.key"

    # Agent CSR — CN must match the agent hostname
    openssl req -new \
        -key "${AGENT_DIR}/agent.key" \
        -out "${AGENT_DIR}/agent.csr" \
        -subj "/C=US/ST=Security/O=FIM Enterprise/OU=Agents/CN=${AGENT_NAME}" \
        2>/dev/null

    # Sign with CA
    openssl x509 -req \
        -in "${AGENT_DIR}/agent.csr" \
        -CA "${CERT_DIR}/ca/ca.crt" \
        -CAkey "${CERT_DIR}/ca/ca.key" \
        -CAcreateserial \
        -out "${AGENT_DIR}/agent.crt" \
        -days ${AGENT_DAYS} \
        -sha256 \
        2>/dev/null

    # Copy CA cert for agent to verify server
    cp "${CERT_DIR}/ca/ca.crt" "${AGENT_DIR}/ca.crt"

    # Clean up CSR
    rm -f "${AGENT_DIR}/agent.csr"

    ok "Agent certificate generated:"
    echo "   Key:  ${AGENT_DIR}/agent.key"
    echo "   Cert: ${AGENT_DIR}/agent.crt"
    echo "   CA:   ${AGENT_DIR}/ca.crt"
    echo ""
    echo "  Copy these 3 files to the agent server:"
    echo "    scp ${AGENT_DIR}/agent.key ${AGENT_DIR}/agent.crt ${AGENT_DIR}/ca.crt ${AGENT_NAME}:/opt/fim/agent/certs/"
    echo ""
    echo "  Then update agent_config.yaml:"
    echo "    server:"
    echo "      url: https://${SERVER_HOST}"
    echo "    tls:"
    echo "      enabled: true"
    echo "      ca_cert: certs/ca.crt"
    echo "      client_cert: certs/agent.crt"
    echo "      client_key: certs/agent.key"
}

# ── Handle new-agent subcommand ───────────────────────────────────────────

if [ "$1" = "new-agent" ]; then
    generate_agent_cert "$2"
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════
# FULL SETUP — CA + Server + First Agent
# ══════════════════════════════════════════════════════════════════════════

log "Setting up mTLS for FIM Enterprise"
log "Server: ${SERVER_HOST} (${SERVER_IP})"
echo ""

# ── 1. Create directory structure ─────────────────────────────────────────

mkdir -p "${CERT_DIR}/ca"
mkdir -p "${CERT_DIR}/server"
mkdir -p "${CERT_DIR}/agents"

# ── 2. Generate CA ────────────────────────────────────────────────────────

if [ -f "${CERT_DIR}/ca/ca.crt" ]; then
    warn "CA already exists at ${CERT_DIR}/ca/ca.crt — skipping"
else
    log "Generating Certificate Authority (CA)..."

    # CA private key
    openssl genrsa -out "${CERT_DIR}/ca/ca.key" 4096 2>/dev/null
    chmod 600 "${CERT_DIR}/ca/ca.key"

    # CA certificate (self-signed)
    openssl req -x509 -new -nodes \
        -key "${CERT_DIR}/ca/ca.key" \
        -sha256 \
        -days ${CA_DAYS} \
        -out "${CERT_DIR}/ca/ca.crt" \
        -subj "/C=US/ST=Security/O=FIM Enterprise/OU=Certificate Authority/CN=FIM Enterprise CA" \
        2>/dev/null

    ok "CA generated: ${CERT_DIR}/ca/ca.crt (valid ${CA_DAYS} days)"
fi

# ── 3. Generate Server Certificate ───────────────────────────────────────

if [ -f "${CERT_DIR}/server/server.crt" ]; then
    warn "Server cert already exists — skipping"
else
    log "Generating server certificate..."

    # Server private key
    openssl genrsa -out "${CERT_DIR}/server/server.key" 2048 2>/dev/null
    chmod 600 "${CERT_DIR}/server/server.key"

    # Server SAN config (supports hostname, FQDN, IP, and localhost)
    cat > "${CERT_DIR}/server/server_san.cnf" << SANEOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
req_extensions = req_ext
distinguished_name = dn

[dn]
C = US
ST = Security
O = FIM Enterprise
OU = Server
CN = ${SERVER_HOST}

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SERVER_HOST}
DNS.2 = $(hostname -s)
DNS.3 = localhost
IP.1 = ${SERVER_IP}
IP.2 = 127.0.0.1
SANEOF

    # Server CSR
    openssl req -new \
        -key "${CERT_DIR}/server/server.key" \
        -out "${CERT_DIR}/server/server.csr" \
        -config "${CERT_DIR}/server/server_san.cnf" \
        2>/dev/null

    # Sign with CA
    openssl x509 -req \
        -in "${CERT_DIR}/server/server.csr" \
        -CA "${CERT_DIR}/ca/ca.crt" \
        -CAkey "${CERT_DIR}/ca/ca.key" \
        -CAcreateserial \
        -out "${CERT_DIR}/server/server.crt" \
        -days ${SERVER_DAYS} \
        -sha256 \
        -extensions req_ext \
        -extfile "${CERT_DIR}/server/server_san.cnf" \
        2>/dev/null

    # Clean up
    rm -f "${CERT_DIR}/server/server.csr" "${CERT_DIR}/server/server_san.cnf"

    ok "Server certificate generated: ${CERT_DIR}/server/server.crt"
fi

# ── 4. Generate First Agent Certificate ──────────────────────────────────

FIRST_AGENT=$(hostname -f)
generate_agent_cert "${FIRST_AGENT}"

# ── 5. Generate Updated nginx Config ─────────────────────────────────────

NGINX_CONF="${CERT_DIR}/fim-mtls.conf"

cat > "${NGINX_CONF}" << 'NGINXEOF'
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — nginx config with mTLS
# ══════════════════════════════════════════════════════════════════════════
# This config enables:
#   - HTTPS on port 443 with server certificate
#   - Client certificate verification for /api/v1/agents/ and /api/v1/scans/
#   - Plain browser access (no client cert) for the web UI and other APIs
#   - HTTP→HTTPS redirect on port 80
# ══════════════════════════════════════════════════════════════════════════

upstream fim_backend {
    server 127.0.0.1:8000;
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name _;

    # ── Server TLS ────────────────────────────────────────────────────
NGINXEOF

# Insert actual cert paths (these contain variables so we write them separately)
cat >> "${NGINX_CONF}" << EOF
    ssl_certificate     ${CERT_DIR}/server/server.crt;
    ssl_certificate_key ${CERT_DIR}/server/server.key;
EOF

cat >> "${NGINX_CONF}" << 'NGINXEOF'
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # ── Client Certificate (mTLS) ────────────────────────────────────
    # 'optional' = request client cert but don't require it globally
    # This allows browsers to access the UI without a client cert,
    # while agent endpoints enforce verification via the backend.
NGINXEOF

cat >> "${NGINX_CONF}" << EOF
    ssl_client_certificate ${CERT_DIR}/ca/ca.crt;
EOF

cat >> "${NGINX_CONF}" << 'NGINXEOF'
    ssl_verify_client optional;
    ssl_verify_depth  2;

    # ── Frontend (no client cert required) ────────────────────────────
    root /opt/fim/web/build;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # ── Agent API endpoints (mTLS enforced) ───────────────────────────
    # These endpoints are called by agents and require a valid client cert.
    # nginx passes the verified CN and verification status to the backend.
    location /api/v1/agents/ {
        if ($ssl_client_verify != SUCCESS) {
            return 403 '{"error": "Client certificate required"}';
        }

        proxy_pass http://fim_backend/api/v1/agents/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Client-CN       $ssl_client_s_dn_cn;
        proxy_set_header X-Client-Verify   $ssl_client_verify;
        proxy_set_header X-Client-Serial   $ssl_client_serial;
    }

    location /api/v1/scans/ {
        if ($ssl_client_verify != SUCCESS) {
            return 403 '{"error": "Client certificate required"}';
        }

        proxy_pass http://fim_backend/api/v1/scans/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Client-CN       $ssl_client_s_dn_cn;
        proxy_set_header X-Client-Verify   $ssl_client_verify;
        proxy_set_header X-Client-Serial   $ssl_client_serial;
    }

    # ── Other API endpoints (no client cert — browser/SSO access) ─────
    location /api/ {
        proxy_pass http://fim_backend/api/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINXEOF

ok "nginx mTLS config generated: ${NGINX_CONF}"

# ── 6. Set Permissions ────────────────────────────────────────────────────

chmod 700 "${CERT_DIR}/ca"
chmod 600 "${CERT_DIR}/ca/ca.key"
chmod 644 "${CERT_DIR}/ca/ca.crt"
chmod 600 "${CERT_DIR}/server/server.key"
chmod 644 "${CERT_DIR}/server/server.crt"

ok "Permissions set"

# ── Summary ───────────────────────────────────────────────────────────────

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  mTLS Setup Complete"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Certificate Authority:"
echo "    ${CERT_DIR}/ca/ca.crt"
echo "    ${CERT_DIR}/ca/ca.key  (KEEP SECURE!)"
echo ""
echo "  Server Certificate:"
echo "    ${CERT_DIR}/server/server.crt"
echo "    ${CERT_DIR}/server/server.key"
echo ""
echo "  Agent Certificate (${FIRST_AGENT}):"
echo "    ${CERT_DIR}/agents/${FIRST_AGENT}/agent.crt"
echo "    ${CERT_DIR}/agents/${FIRST_AGENT}/agent.key"
echo ""
echo "  nginx Config:"
echo "    ${NGINX_CONF}"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  NEXT STEPS:"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  1. Deploy nginx config:"
echo "     cp /etc/nginx/conf.d/fim.conf /etc/nginx/conf.d/fim.conf.bak"
echo "     cp ${NGINX_CONF} /etc/nginx/conf.d/fim.conf"
echo "     nginx -t && systemctl reload nginx"
echo ""
echo "  2. Copy agent certs to agent server:"
echo "     mkdir -p /opt/fim/agent/certs"
echo "     cp ${CERT_DIR}/agents/${FIRST_AGENT}/agent.* /opt/fim/agent/certs/"
echo "     cp ${CERT_DIR}/agents/${FIRST_AGENT}/ca.crt /opt/fim/agent/certs/"
echo ""
echo "  3. Update agent_config.yaml (see below)"
echo ""
echo "  4. For new agents, run:"
echo "     $0 new-agent <hostname>"
echo ""
echo "═══════════════════════════════════════════════════════════════"

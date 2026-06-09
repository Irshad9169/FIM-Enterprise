# FIM System Architecture

## 🏗️ High-Level Architecture
┌─────────────────────────────────────────────────────────────────────────────┐
│ ENTERPRISE FIM SYSTEM │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐ ┌──────────────────────┐ ┌──────────────┐
│ │ │ │ │ │
│ AGENT LAYER │ ──────→ │ APPLICATION │ ──────→ │ DATA LAYER │
│ (Monitored │ ←────── │ LAYER │ ←────── │ │
│ Endpoints) │ │ │ │ │
│ │ │ │ │ │
└──────────────────┘ └──────────────────────┘ └──────────────┘


---

## 📊 Detailed Component Architecture
┌─────────────────────────────────────────────────────────────────────────────────┐
│ CLIENTS │
├─────────────────────────────────────────────────────────────────────────────────┤
│ │
│ ┌────────────────┐ ┌────────────────┐ ┌────────────────┐ │
│ │ FIM Agents │ │ Web Dashboard │ │ REST API │ │
│ │ (Python) │ │ (React/Vue) │ │ Clients │ │
│ │ Port: N/A │ │ Port: 3000 │ │ (curl/etc) │ │
│ └────────────────┘ └────────────────┘ └────────────────┘ │
│ │ │ │ │
│ │ POST /api/v1/scans │ HTTPS │ HTTPS │
│ │ POST /heartbeat │ │ │
│ └────────────────────────┴────────────────────────┘ │
│ │ │
└──────────────────────────────────┼──────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ LOAD BALANCER │
├─────────────────────────────────────────────────────────────────────────────────┤
│ │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ Nginx / HAProxy │ │
│ │ • SSL Termination │ │
│ │ • Rate Limiting (10 req/s per IP) │ │
│ │ • Request Routing │ │
│ │ • Health Checks │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
└──────────────────────────────────┼──────────────────────────────────────────────┘
│
┌──────────────┼──────────────┐
│ │ │
▼ ▼ ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ APPLICATION SERVERS │
├─────────────────────────────────────────────────────────────────────────────────┤
│ │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│ │ Server 1 │ │ Server 2 │ │ Server 3 │ │
│ │ Port: 8000 │ │ Port: 8000 │ │ Port: 8000 │ │
│ └──────────────┘ └──────────────┘ └──────────────┘ │
│ │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ FastAPI Application │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ API Layer │ │ │
│ │ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │ │ │
│ │ │ │ Auth │ │ Agents │ │ Scans │ │ Alerts │ │ │ │
│ │ │ │ /auth │ │ /agents │ │ /scans │ │ /alerts │ │ │ │
│ │ │ └──────────┘ └──────────┘ └──────────┘ └──────────┘ │ │ │
│ │ │ ┌──────────┐ ┌──────────┐ ┌──────────┐ │ │ │
│ │ │ │Baselines │ │ Health │ │ Stats │ │ │ │
│ │ │ │/baselines│ │ /health │ │ /actions │ │ │ │
│ │ │ └──────────┘ └──────────┘ └──────────┘ │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ │ │ │ │
│ │ ▼ │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ Business Logic Layer │ │ │
│ │ │ ┌────────────────┐ ┌────────────────┐ │ │ │
│ │ │ │ Change │ │ Agent Health │ │ │ │
│ │ │ │ Detector │ │ Monitor │ │ │ │
│ │ │ │ • Compare │ │ • Track status │ │ │ │
│ │ │ │ • Generate │ │ • Heartbeats │ │ │ │
│ │ │ │ alerts │ │ • Stale detect │ │ │ │
│ │ │ └────────────────┘ └────────────────┘ │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ │ │ │ │
│ │ ▼ │ │
│ │ ┌─────────────────────────────────────────────────────────┐ │ │
│ │ │ Data Access Layer (SQLAlchemy ORM) │ │ │
│ │ │ • Async sessions │ │ │
│ │ │ • Connection pooling (50 + 100 overflow) │ │ │
│ │ │ • Transaction management │ │ │
│ │ └─────────────────────────────────────────────────────────┘ │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
└──────────────────────────────────┼──────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│ DATABASE LAYER │
├─────────────────────────────────────────────────────────────────────────────────┤
│ │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ PostgreSQL 15+ (Primary) │ │
│ │ • Port: 5432 │ │
│ │ • Max Connections: 500 │ │
│ │ • Shared Buffers: 2GB │ │
│ │ • Schema: fim │ │
│ │ │ │
│ │ Tables: │ │
│ │ ├─ users (auth) │ │
│ │ ├─ agents (monitored endpoints) │ │
│ │ ├─ scans (scan history + JSONB file data) │ │
│ │ ├─ baselines (approved states) │ │
│ │ ├─ alerts (change notifications) │ │
│ │ ├─ policies (monitoring rules) │ │
│ │ ├─ agent_health_events (health tracking) │ │
│ │ ├─ audit_logs (user actions) │ │
│ │ ├─ alert_rules (custom rules) │ │
│ │ ├─ compliance_frameworks (PCI/HIPAA/etc) │ │
│ │ ├─ compliance_controls │ │
│ │ ├─ compliance_violations │ │
│ │ ├─ whitelist_rules (suppression rules) │ │
│ │ └─ whitelist_matches (match log) │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │ │
│ ▼ │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ PostgreSQL Replica (Optional - Read-only) │ │
│ │ • Streaming Replication │ │
│ │ • Read queries load balancing │ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ │
└─────────────────────────────────────────────────────────────────────────────────┘



---

## 🔄 Data Flow Diagrams

### 1. Agent Scan Submission Flow
┌─────────┐ ┌──────────┐
│ Agent │ │ Database │
└────┬────┘ └────┬─────┘
│ │
│ 1. Scan files (SHA256 hash, permissions, owner, etc.) │
│────────────────────────────────────────────────────────► │
│ │
│ 2. POST /api/v1/scans/submit │
│ {agent_id, timestamp, files[]} │
│────────────────────────────────────────────────────────► │
│ │ │
│ 3. Verify agent │ │
│ ├──────────────►│
│ │ SELECT agents │
│ │◄──────────────┤
│ │ │
│ 4. Store scan │ │
│ ├──────────────►│
│ │ INSERT scans │
│ │ │
│ 5. Get active baseline │
│ ├──────────────►│
│ │◄──────────────┤
│ │ │
│ 6. Compare files (Change Detector) │
│ - New files │
│ - Modified files │
│ - Deleted files │
│ │ │
│ 7. Generate alerts │ │
│ ├──────────────►│
│ │ INSERT alerts │
│ │ │
│ 8. Update scan stats │ │
│ ├──────────────►│
│ │ UPDATE scans │
│ │ │
│ ◄─────────────────────────────────────────────────┤ │
│ 9. Response: {scan_id, alerts_created: 263} │ │
│ │


### 2. Baseline Creation Flow
┌─────────┐ ┌──────────┐
│ Admin │ │ Database │
└────┬────┘ └────┬─────┘
│ │
│ 1. POST /api/v1/auth/login │
│────────────────────────────────────────────────────────► │
│ │ │
│ 2. Verify user │ │
│ ├──────────────►│
│ │ SELECT users │
│ │◄──────────────┤
│ ◄─────────────────────────────────────────────────┤ │
│ 3. JWT Token │ │
│ │
│ 4. POST /api/v1/baselines/create │
│ {agent_id, scan_id, baseline_name} │
│────────────────────────────────────────────────────────► │
│ │ │
│ 5. Get scan data │ │
│ ├──────────────►│
│ │ SELECT scans │
│ │◄──────────────┤
│ │ │
│ 6. Deactivate old baselines │ │
│ ├──────────────►│
│ │ UPDATE │
│ │ is_active=F │
│ │ │
│ 7. Create new baseline │ │
│ ├──────────────►│
│ │ INSERT │
│ │ baselines │
│ ◄─────────────────────────────────────────────────┤ │
│ 8. {baseline_id, file_count: 1259} │ │
│ │

### 3. Alert Workflow
┌──────────────┐ ┌──────────┐
│ Change │ │ Database │
│ Detector │ └────┬─────┘
└──────┬───────┘ │
│ │
│ 1. Detect change (hash mismatch) │
│────────────────────────────────────────────────────► │
│ │
│ 2. Calculate severity │
│ - Critical files? → critical │
│ - /etc/? → high │
│ - /usr/sbin/? → medium │
│ │
│ 3. Create alert │
│────────────────────────────────────────────────────────► │
│ INSERT alerts (file_path, severity, change_details) │ │
│ │ │
│ │
┌──────┴───────┐ │
│ Admin/ │ │
│ Analyst │ │
└──────┬───────┘ │
│ │
│ 4. GET /api/v1/alerts/?severity=critical │
│────────────────────────────────────────────────────────► │
│ │ │
│ 5. Query │ │
│ ├────────►│
│ │◄────────┤
│ ◄─────────────────────────────────────────────────────┤ │
│ 6. List of alerts │ │
│ │
│ 7. POST /alerts/actions/acknowledge │
│ {alert_id, notes} │
│────────────────────────────────────────────────────────► │
│ │ │
│ 8. Update ├────────►│
│ status │ UPDATE │
│ notes │ alerts │
│ │ │
│ ◄─────────────────────────────────────────────────────┤ │
│ 9. {success: true} │ │
│ │


---

## 🔐 Security Architecture
┌─────────────────────────────────────────────────────────────────────┐
│ SECURITY LAYERS │
└─────────────────────────────────────────────────────────────────────┘

Layer 1: Network Security
┌──────────────────────────────────────────────────────────────┐
│ • Firewall rules (iptables/firewalld) │
│ • VPN/Private network for agents │
│ • Rate limiting (10 req/s per IP) │
└──────────────────────────────────────────────────────────────┘
▼
Layer 2: TLS/SSL
┌──────────────────────────────────────────────────────────────┐
│ • HTTPS only (TLS 1.2+) │
│ • Certificate validation │
│ • Strong ciphers only │
└──────────────────────────────────────────────────────────────┘
▼
Layer 3: Application Authentication
┌──────────────────────────────────────────────────────────────┐
│ Admin Users: │
│ • JWT tokens (HS256) │
│ • 24-hour expiration │
│ • Bcrypt password hashing (12 rounds) │
│ │
│ Agents: (Future - Currently no agent auth) │
│ • Per-agent API keys │
│ • Token rotation │
└──────────────────────────────────────────────────────────────┘
▼
Layer 4: Authorization
┌──────────────────────────────────────────────────────────────┐
│ • Role-based access control (RBAC) │
│ - admin: full access │
│ - analyst: view + acknowledge alerts │
│ - viewer: read-only │
│ • Endpoint-level permissions │
└──────────────────────────────────────────────────────────────┘
▼
Layer 5: Data Security
┌──────────────────────────────────────────────────────────────┐
│ • SQL injection protection (parameterized queries) │
│ • Input validation (Pydantic models) │
│ • Output sanitization │
│ • Audit logging │
└──────────────────────────────────────────────────────────────┘
▼
Layer 6: Database Security
┌──────────────────────────────────────────────────────────────┐
│ • Dedicated database user (fim_app) │
│ • Schema-level isolation (fim schema) │
│ • Row-level security (future) │
│ • Encrypted backups │
└──────────────────────────────────────────────────────────────┘


---

## 📦 Component Details

### FastAPI Application

```python
Technology: FastAPI 0.104.1
Server: Uvicorn (ASGI)
Workers: 4 (production)
Port: 8000

Key Features:
├── Async request handling
├── Automatic OpenAPI docs (/api/docs)
├── Pydantic validation
├── Dependency injection
└── Background tasks

Performance:
├── Request latency: <50ms (avg)
├── Throughput: 1000+ req/s (single worker)
└── Concurrent connections: 10,000+

Database Schema
Schema: fim
Tables: 14
Total Size: ~500MB (with 1,562 alerts)

Key Indexes:
├── idx_alerts_agent (agent_id)
├── idx_alerts_detected_at (detected_at DESC)
├── idx_alerts_severity (severity)
├── idx_alerts_status (status)
├── idx_agents_last_heartbeat (last_heartbeat DESC)
└── idx_scans_agent (agent_id, started_at DESC)

Connection Pool:
├── Pool size: 50
├── Max overflow: 100
├── Total capacity: 150 connections
└── Current usage: 2% (3/150)

Agent Architecture
 Component: fim_agent.py
Language: Python 3.11+
Mode: Daemon (systemd service)

Capabilities:
├── File scanning (recursive)
├── SHA256 hashing
├── Metadata collection (perms, owner, size, mtime)
├── Heartbeat (every 5 min)
├── Auto-registration
├── Configurable paths & exclusions
└── Error recovery

Performance:
├── Scan speed: ~5000 files/sec
├── Memory usage: <100MB
├── CPU usage: <5% (during scan)
└── Network: <1MB per scan (compressed)

Scan Interval: 6 hours (default)

🔄 State Diagrams
Agent Lifecycle
┌─────────┐
│  NEW    │  (First boot)
└────┬────┘
     │
     │ POST /agents/ (register)
     ▼
┌─────────┐
│ ONLINE  │ ◄──────┐
└────┬────┘        │
     │             │ Heartbeat received
     │ No heartbeat│ (< 10 min)
     │ for 10 min  │
     ▼             │
┌─────────┐        │
│ STALE   │────────┘
└────┬────┘
     │
     │ No heartbeat
     │ for 1 hour
     ▼
┌─────────┐
│ OFFLINE │
└─────────┘

Alert Lifecycle

┌──────────────┐
│ DETECTED     │  (Change detected)
└──────┬───────┘
       │
       │ Auto-created by Change Detector
       ▼
┌──────────────┐
│ OPEN         │ ◄──────────────┐
└──────┬───────┘                │
       │                         │
       │ POST /acknowledge       │ POST /reopen
       ▼                         │
┌──────────────┐                │
│ ACKNOWLEDGED │                │
└──────┬───────┘                │
       │                         │
       │ POST /resolve           │
       ▼                         │
┌──────────────┐                │
│ RESOLVED     │────────────────┘
└──────────────┘
       │
       │ (Optional: Auto-archive after 90 days)
       ▼
┌──────────────┐
│ ARCHIVED     │
└──────────────┘

 Performance Characteristics
 
Throughput (Single Server)
OperationRequests/secLatency (p95)
GET /agents2000+10ms
GET /alerts1500+25ms
POST /scans/submit100+150ms
POST /baselines/create50+300ms
GET /stats500+50ms

Scalability Limits
ResourceCurrentTestedTheoretical Max
Agents2100 concurrent5000+
Scans/hour0.33100833 (5000 agents ÷ 6h)
Alerts1,562100,000Millions
Database size500MB50GB1TB+
Concurrent API calls101001000+

Resource Usage (per server)
CPU: 2-4 cores (8 cores recommended for 1000+ agents)
RAM: 2GB minimum, 8GB recommended
Disk: 50GB minimum, 500GB recommended
Network: 100Mbps minimum, 1Gbps recommended

Database Server:
CPU: 4-8 cores
RAM: 8GB minimum (shared_buffers = 2GB)
Disk: SSD required, 1TB recommended
IOPS: 3000+ recommended


🔧 Technology Choices & Rationale
Why FastAPI?
✅ Async by default - handles 10,000+ concurrent connections
✅ Automatic validation - Pydantic catches bad data before DB
✅ Auto-generated docs - /api/docs for free
✅ Type hints - better IDE support, fewer bugs
✅ Performance - 2-3x faster than Flask

Why PostgreSQL?
✅ JSONB support - stores file scan data efficiently
✅ Mature - battle-tested, 25+ years
✅ ACID compliance - data integrity guaranteed
✅ Advanced indexing - GIN indexes for JSONB queries
✅ Partitioning - scale to billions of records

Why SQLAlchemy (Async)?
✅ ORM + Raw SQL - flexibility when needed
✅ Connection pooling - efficient resource usage
✅ Migration support - Alembic integration
✅ Type safety - models define schema

Why JWT for Auth?
✅ Stateless - no session storage needed
✅ Scalable - works across multiple servers
✅ Standard - widely supported
✅ Secure - signed tokens, can't be tampered

🚀 Deployment Topologies
1. Single Server (Development/Small Teams)
┌──────────────────────────────┐
│  Single Server               │
│  ├── FastAPI (port 8000)     │
│  ├── PostgreSQL (port 5432)  │
│  └── Nginx (port 443)        │
└──────────────────────────────┘

Capacity: 50-100 agents
Cost: $50-100/month

2. Separated Tiers (Production)
┌────────────┐     ┌─────────────┐     ┌──────────────┐
│  Nginx     │────→│  FastAPI    │────→│  PostgreSQL  │
│  (LB/SSL)  │     │  Servers    │     │  Primary     │
│            │     │  (2-3 nodes)│     │              │
└────────────┘     └─────────────┘     └──────┬───────┘
                                               │
                                               ├→ Replica (RO)
                                               └→ Replica (RO)

Capacity: 500-1000 agents
Cost: $300-500/month

3. High Availability (Enterprise)
            ┌─────────────┐
            │   HAProxy   │
            │  (Active)   │
            └──────┬──────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
   ┌────▼───┐ ┌───▼────┐ ┌──▼─────┐
   │FastAPI │ │FastAPI │ │FastAPI │
   │Server 1│ │Server 2│ │Server 3│
   └────┬───┘ └───┬────┘ └──┬─────┘
        │         │          │
        └─────────┼──────────┘
                  │
        ┌─────────▼──────────┐
        │  PostgreSQL        │
        │  Primary (Write)   │
        └─────────┬──────────┘
                  │
        ┌─────────┼──────────┐
        │         │          │
   ┌────▼───┐ ┌──▼─────┐ ┌─▼──────┐
   │Replica │ │Replica │ │Standby │
   │(Read)  │ │(Read)  │ │(Failover)│
   └────────┘ └────────┘ └────────┘

Capacity: 5000+ agents
Cost: $1000-2000/month
Uptime: 99.9%+

📁 Directory Structure

/opt/fim/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI application entry
│   ├── api/                       # API route handlers
│   │   ├── __init__.py
│   │   ├── agents.py              # Agent CRUD
│   │   ├── alerts.py              # Alert listing/filtering
│   │   ├── alert_actions.py       # Acknowledge/resolve
│   │   ├── auth.py                # JWT login
│   │   ├── baselines.py           # Baseline management
│   │   ├── scans.py               # Scan submission
│   │   ├── agent_health.py        # Health monitoring
│   │   └── health.py              # System health check
│   ├── core/                      # Core utilities
│   │   ├── __init__.py
│   │   ├── config.py              # Settings (Pydantic)
│   │   ├── database.py            # DB connection pool
│   │   └── security.py            # JWT + password hashing
│   ├── models/                    # Database models
│   │   ├── __init__.py
│   │   └── models.py              # SQLAlchemy models
│   └── services/                  # Business logic
│       ├── __init__.py
│       ├── change_detector.py     # Compare scans to baseline
│       └── agent_health.py        # Health monitoring logic
├── agent/                         # Agent code
│   ├── fim_agent.py               # Main agent
│   ├── config/
│   │   └── agent_config.yaml
│   └── logs/
│       └── fim_agent.log
├── database/
│   └── schema.sql                 # Initial schema
├── fim-backups/
│   ├── scripts/
│   │   ├── backup_fim.sh
│   │   └── restore_fim.sh
│   ├── dumps/                     # Backup files
│   └── logs/                      # Backup logs
├── docs/
│   ├── ARCHITECTURE.md            # This file
│   ├── API.md                     # API docs (next)
│   └── PERFORMANCE.md             # Tuning guide (next)
├── scripts/
│   └── create_admin.py            # Bootstrap admin user
├── .env                           # Environment config
├── requirements.txt               # Python dependencies
└── README.md                      # Main documentation

Next: API Documentation | Performance Tuning Guide


#!/usr/bin/env python3
"""
Populate affected_hosts JSONB for existing correlation groups
"""
import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

# Read DATABASE_URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    env_file = "/opt/fim/.env"
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if line.startswith("DATABASE_URL"):
                    DATABASE_URL = line.split("=", 1)[1].strip()
                    break

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    exit(1)

async def populate_hosts():
    engine = create_async_engine(DATABASE_URL)
    
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT id, report_id, file_pattern
            FROM fim.correlation_groups
            WHERE affected_hosts IS NULL
        """))
        
        groups = result.fetchall()
        print(f"Found {len(groups)} groups to update")
        
        for group_id, report_id, file_pattern in groups:
            result = await conn.execute(text("""
                SELECT 
                    rc.alert_id,
                    a.agent_id,
                    a.severity,
                    a.detected_at,
                    rc.agent_hostname
                FROM fim.report_changes rc
                JOIN fim.alerts a ON rc.alert_id = a.id
                WHERE rc.correlation_group_id = :group_id
                ORDER BY a.detected_at
            """), {'group_id': str(group_id)})
            
            alerts = result.fetchall()
            
            if not alerts:
                print(f"  ⚠️ No alerts for group {group_id}")
                continue
            
            hosts = []
            for alert_id, agent_id, severity, detected_at, hostname in alerts:
                hosts.append({
                    "alert_id": str(alert_id),
                    "agent_id": str(agent_id),
                    "hostname": hostname or "unknown",
                    "severity": severity,
                    "detected_at": detected_at.isoformat() if detected_at else None
                })
            
            hostnames = [h['hostname'] for h in hosts if h['hostname'] != 'unknown']
            common_domain = ""
            if hostnames:
                parts = [h.split('.') for h in hostnames if '.' in h]
                if parts:
                    for i in range(1, min(len(p) for p in parts) + 1):
                        suffixes = ['.'.join(p[-i:]) for p in parts]
                        if len(set(suffixes)) == 1:
                            common_domain = suffixes[0]
                        else:
                            break
            
            hosts_json = json.dumps({
                'hosts': hosts,
                'common_domain': common_domain,
                'time_range': {
                    'start': hosts[0]['detected_at'] if hosts else None,
                    'end': hosts[-1]['detected_at'] if hosts else None
                }
            })
            
            # FIXED: Use CAST instead of :: to avoid parameter mixing
            await conn.execute(text("""
                UPDATE fim.correlation_groups
                SET affected_hosts = CAST(:hosts AS jsonb)
                WHERE id = :group_id
            """), {
                'hosts': hosts_json,
                'group_id': str(group_id)
            })
            
            print(f"  ✅ {file_pattern} - {len(hosts)} hosts")
        
        print(f"\n✅ Updated {len(groups)} groups")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(populate_hosts())

#!/usr/bin/env python3
"""
Generate test alerts for FIM dashboard testing
"""
import asyncio
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import json
from pathlib import Path

# Load environment from .env file
env_file = Path("/opt/fim/.env")
env_vars = {}
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            env_vars[key.strip()] = value.strip()

DATABASE_URL = env_vars.get('DATABASE_URL', 'postgresql+asyncpg://fim_user:SecurePassword123!@localhost/fim_db')

async def generate_test_alerts():
    print(f"Connecting to database...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get first agent
        result = await session.execute(text("SELECT id, hostname FROM fim.agents LIMIT 1"))
        agent = result.fetchone()
        
        if not agent:
            print("❌ No agents found. Register an agent first.")
            return
        
        agent_id, hostname = agent
        print(f"Found agent: {hostname} ({agent_id})")
        
        # Sample test alerts
        test_alerts = [
            {
                "file_path": "/etc/passwd",
                "severity": "critical",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "abc123def456",
                    "size": 2048,
                    "permissions": "0644",
                    "owner": 0,
                    "modified_time": "2025-01-01T10:00:00"
                },
                "current_state": {
                    "hash": "xyz789uvw012",
                    "size": 2100,
                    "permissions": "0777",
                    "owner": 1000,
                    "modified_time": "2025-01-02T11:30:00"
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+52 bytes",
                    "permissions_changed": True,
                    "old_perms": "0644",
                    "new_perms": "0777",
                    "owner_changed": True
                }
            },
            {
                "file_path": "/etc/shadow",
                "severity": "critical",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "shadow123",
                    "size": 1024,
                    "permissions": "0600",
                    "owner": 0
                },
                "current_state": {
                    "hash": "shadow456",
                    "size": 1100,
                    "permissions": "0600",
                    "owner": 0
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+76 bytes"
                }
            },
            {
                "file_path": "/var/www/html/index.php",
                "severity": "high",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "web123",
                    "size": 5120,
                    "permissions": "0644"
                },
                "current_state": {
                    "hash": "web456",
                    "size": 5200,
                    "permissions": "0644"
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+80 bytes"
                }
            },
            {
                "file_path": "/home/user/config.conf",
                "severity": "medium",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "config123",
                    "size": 512,
                    "permissions": "0644"
                },
                "current_state": {
                    "hash": "config456",
                    "size": 520,
                    "permissions": "0644"
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+8 bytes"
                }
            },
            {
                "file_path": "/tmp/suspicious_script.sh",
                "severity": "critical",
                "alert_type": "addition",
                "previous_state": {},
                "current_state": {
                    "hash": "malware789",
                    "size": 2048,
                    "permissions": "0755",
                    "owner": 1000
                },
                "change_details": {
                    "hash_changed": True
                }
            },
            {
                "file_path": "/etc/crontab",
                "severity": "high",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "cron123",
                    "size": 1024,
                    "permissions": "0644"
                },
                "current_state": {
                    "hash": "cron456",
                    "size": 1100,
                    "permissions": "0644"
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+76 bytes"
                }
            },
            {
                "file_path": "/bin/bash",
                "severity": "critical",
                "alert_type": "modification",
                "previous_state": {
                    "hash": "bash_original_hash",
                    "size": 1234567,
                    "permissions": "0755",
                    "owner": 0
                },
                "current_state": {
                    "hash": "bash_modified_hash",
                    "size": 1234600,
                    "permissions": "0755",
                    "owner": 0
                },
                "change_details": {
                    "hash_changed": True,
                    "size_changed": True,
                    "size_diff": "+33 bytes"
                }
            },
            {
                "file_path": "/var/log/auth.log",
                "severity": "medium",
                "alert_type": "deletion",
                "previous_state": {
                    "hash": "authlog123",
                    "size": 102400,
                    "permissions": "0640"
                },
                "current_state": {},
                "change_details": {
                    "hash_changed": True
                }
            },
        ]
        
        # Insert alerts
        print(f"\nCreating {len(test_alerts)} test alerts...")
        for alert_data in test_alerts:
            alert_id = uuid.uuid4()
            
            query = text("""
                INSERT INTO fim.alerts 
                (id, agent_id, alert_type, severity, file_path, 
                 previous_state, current_state, change_details, 
                 status, detected_at, created_at)
                VALUES 
                (:id, :agent_id, :alert_type, :severity, :file_path,
                 :previous_state::jsonb, :current_state::jsonb, :change_details::jsonb,
                 :status, :detected_at, :created_at)
            """)
            
            await session.execute(query, {
                'id': str(alert_id),
                'agent_id': str(agent_id),
                'alert_type': alert_data['alert_type'],
                'severity': alert_data['severity'],
                'file_path': alert_data['file_path'],
                'previous_state': json.dumps(alert_data['previous_state']),
                'current_state': json.dumps(alert_data['current_state']),
                'change_details': json.dumps(alert_data['change_details']),
                'status': 'open',
                'detected_at': datetime.utcnow(),
                'created_at': datetime.utcnow()
            })
            
            print(f"  ✅ {alert_data['severity']:8s} alert: {alert_data['file_path']}")
        
        await session.commit()
        print(f"\n✅ Generated {len(test_alerts)} test alerts for agent: {hostname}")
        
        # Show summary
        result = await session.execute(text("""
            SELECT severity, COUNT(*) 
            FROM fim.alerts 
            WHERE agent_id = :agent_id 
            GROUP BY severity
            ORDER BY 
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                END
        """), {'agent_id': str(agent_id)})
        
        print("\n📊 Alert Summary:")
        for severity, count in result.fetchall():
            print(f"   {severity:8s}: {count}")
    
    await engine.dispose()

if __name__ == "__main__":
    try:
        asyncio.run(generate_test_alerts())
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

#!/usr/bin/env python3
"""
Sync exclusion rules from text file to database
Usage: python sync_exclusions.py
"""

import asyncio
import re
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import uuid
from datetime import datetime

# Database configuration
DATABASE_URL = "postgresql+asyncpg://fim_app:FIM_Secure_Pass_2025!@localhost/fim_db"

# Exclusions file path
EXCLUSIONS_FILE = "/opt/fim/config/exclusions.txt"


async def load_exclusions_from_file(file_path: str):
    """Load exclusions from text file"""
    exclusions = []
    
    if not Path(file_path).exists():
        print(f"❌ File not found: {file_path}")
        return exclusions
    
    with open(file_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            # Strip whitespace
            line = line.strip()
            
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            
            # Determine rule type
            if line.startswith('regex:'):
                rule_type = 'regex'
                match_value = line[6:].strip()
                rule_name = f"Regex: {match_value[:50]}"
            elif '*' in line:
                rule_type = 'glob'
                match_value = line
                rule_name = f"Pattern: {match_value}"
            else:
                rule_type = 'path'
                match_value = line
                rule_name = f"Exact: {match_value}"
            
            exclusions.append({
                'rule_name': rule_name,
                'rule_type': rule_type,
                'match_value': match_value,
                'line_num': line_num
            })
    
    return exclusions


async def sync_to_database(exclusions):
    """Sync exclusions to database"""
    
    # Create async engine
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        try:
            # Get admin user ID
            result = await session.execute(
                text("SELECT id FROM fim.users WHERE username = 'admin' LIMIT 1")
            )
            admin_id = result.scalar_one_or_none()
            
            if not admin_id:
                print("❌ Admin user not found")
                return
            
            # Clear existing auto-synced rules
            await session.execute(
                text("""
                    DELETE FROM fim.whitelist_rules 
                    WHERE reason LIKE 'Auto-synced from exclusions.txt%'
                """)
            )
            print("🗑️  Cleared existing auto-synced rules")
            
            # Insert new rules
            inserted = 0
            for excl in exclusions:
                rule_id = str(uuid.uuid4())
                
                await session.execute(
                    text("""
                        INSERT INTO fim.whitelist_rules (
                            id, rule_name, rule_type, match_value, reason,
                            is_active, is_temporary, created_by, created_at, match_count
                        ) VALUES (
                            :id, :rule_name, :rule_type, :match_value, :reason,
                            true, false, :created_by, NOW(), 0
                        )
                    """),
                    {
                        'id': rule_id,
                        'rule_name': excl['rule_name'],
                        'rule_type': excl['rule_type'],
                        'match_value': excl['match_value'],
                        'reason': f"Auto-synced from exclusions.txt (line {excl['line_num']})",
                        'created_by': admin_id
                    }
                )
                inserted += 1
                print(f"  ✅ Added: {excl['match_value']}")
            
            await session.commit()
            print(f"\n✅ Successfully synced {inserted} exclusion rules to database")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            await session.rollback()
        finally:
            await engine.dispose()


async def main():
    print("=" * 60)
    print("FIM Exclusion Sync Tool")
    print("=" * 60)
    print(f"📄 Loading exclusions from: {EXCLUSIONS_FILE}\n")
    
    # Load exclusions
    exclusions = await load_exclusions_from_file(EXCLUSIONS_FILE)
    
    if not exclusions:
        print("⚠️  No exclusions found in file")
        return
    
    print(f"📋 Found {len(exclusions)} exclusion rules:\n")
    for excl in exclusions:
        print(f"  [{excl['rule_type']:5}] {excl['match_value']}")
    
    print("\n" + "=" * 60)
    print("🔄 Syncing to database...\n")
    
    # Sync to database
    await sync_to_database(exclusions)
    
    print("=" * 60)
    print("✅ Sync complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

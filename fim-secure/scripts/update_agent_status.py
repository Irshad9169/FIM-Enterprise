#!/usr/bin/env python3
"""
Update agent status based on last heartbeat
Run this periodically (e.g., every minute via cron)
"""
import asyncio
from datetime import datetime, timedelta
from sqlalchemy import text
from app.core.database import get_async_session

async def update_agent_statuses():
    async with get_async_session() as db:
        # Mark agents as offline if heartbeat > 5 minutes old
        await db.execute(text("""
            UPDATE fim.agents 
            SET status = 'offline' 
            WHERE status = 'online' 
              AND last_seen < NOW() - INTERVAL '5 minutes'
        """))
        
        await db.commit()
        print(f"✅ Updated agent statuses at {datetime.now()}")

if __name__ == "__main__":
    asyncio.run(update_agent_statuses())

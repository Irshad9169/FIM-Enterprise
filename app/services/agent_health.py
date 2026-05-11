"""
Agent Health Monitoring Service
Tracks agent online/offline status and detects stale agents
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from datetime import datetime, timedelta
import logging
import uuid

from app.models.models import Agent

logger = logging.getLogger(__name__)

class AgentHealthMonitor:
    """Monitor agent health and detect stale/offline agents"""
    
    @staticmethod
    async def check_agent_health(agent_id: uuid.UUID, db: AsyncSession) -> dict:
        """Check if a specific agent is healthy"""
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        
        if not agent:
            return {'error': 'Agent not found'}
        
        is_healthy = AgentHealthMonitor._is_agent_healthy(agent)
        time_since_last_heartbeat = None
        
        if agent.last_heartbeat:
            time_since_last_heartbeat = (datetime.utcnow() - agent.last_heartbeat).total_seconds()
        
        return {
            'agent_id': str(agent.id),
            'hostname': agent.hostname,
            'status': agent.status,
            'is_healthy': is_healthy,
            'last_heartbeat': agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
            'seconds_since_heartbeat': time_since_last_heartbeat,
            'expected_interval': agent.expected_heartbeat_interval,
            'timeout_threshold': agent.heartbeat_timeout
        }
    
    @staticmethod
    async def get_stale_agents(db: AsyncSession) -> list:
        """Get all agents that haven't reported in recently"""
        result = await db.execute(
            select(Agent).where(
                Agent.last_heartbeat < datetime.utcnow() - timedelta(minutes=10)
            )
        )
        stale_agents = result.scalars().all()
        
        return [
            {
                'agent_id': str(a.id),
                'hostname': a.hostname,
                'last_heartbeat': a.last_heartbeat.isoformat() if a.last_heartbeat else None,
                'minutes_offline': int((datetime.utcnow() - a.last_heartbeat).total_seconds() / 60) if a.last_heartbeat else None
            }
            for a in stale_agents
        ]
    
    @staticmethod
    async def update_agent_health_status(db: AsyncSession):
        """
        Update health status for all agents
        Called periodically (e.g., every 5 minutes)
        """
        # Get all agents
        result = await db.execute(select(Agent))
        agents = result.scalars().all()
        
        updated_count = 0
        went_offline = []
        came_online = []
        
        for agent in agents:
            was_healthy = agent.is_healthy
            is_healthy = AgentHealthMonitor._is_agent_healthy(agent)
            
            # Status changed
            if was_healthy != is_healthy:
                agent.is_healthy = is_healthy
                
                # Log health event
                event_type = 'came_online' if is_healthy else 'went_offline'
                if is_healthy:
                    came_online.append(agent.hostname)
                else:
                    went_offline.append(agent.hostname)
                
                await db.execute(
                    text("""
                        INSERT INTO fim.agent_health_events 
                        (agent_id, event_type, previous_status, new_status, details)
                        VALUES (:agent_id, :event_type, :prev, :new, :details::jsonb)
                    """),
                    {
                        'agent_id': str(agent.id),
                        'event_type': event_type,
                        'prev': 'healthy' if was_healthy else 'unhealthy',
                        'new': 'healthy' if is_healthy else 'unhealthy',
                        'details': '{"checked_at": "' + datetime.utcnow().isoformat() + '"}'
                    }
                )
                
                updated_count += 1
        
        await db.commit()
        
        logger.info(f"Health check complete: {updated_count} status changes, {len(went_offline)} offline, {len(came_online)} online")
        
        return {
            'checked': len(agents),
            'status_changes': updated_count,
            'went_offline': went_offline,
            'came_online': came_online
        }
    
    @staticmethod
    def _is_agent_healthy(agent: Agent) -> bool:
        """Determine if agent is healthy based on heartbeat"""
        if not agent.last_heartbeat:
            return False
        
        timeout = agent.heartbeat_timeout or 600  # Default 10 min
        time_since = (datetime.utcnow() - agent.last_heartbeat).total_seconds()
        
        return time_since < timeout
    
    @staticmethod
    async def get_health_summary(db: AsyncSession) -> dict:
        """Get overall agent health summary"""
        result = await db.execute(
            text("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN is_healthy THEN 1 ELSE 0 END) as healthy,
                    SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online,
                    SUM(CASE WHEN last_heartbeat < NOW() - INTERVAL '1 hour' THEN 1 ELSE 0 END) as stale_1h,
                    SUM(CASE WHEN last_heartbeat < NOW() - INTERVAL '24 hours' THEN 1 ELSE 0 END) as stale_24h
                FROM fim.agents
            """)
        )
        
        stats = result.one()
        
        return {
            'total_agents': stats.total or 0,
            'healthy': stats.healthy or 0,
            'unhealthy': (stats.total or 0) - (stats.healthy or 0),
            'online': stats.online or 0,
            'stale_last_hour': stats.stale_1h or 0,
            'stale_last_day': stats.stale_24h or 0
        }

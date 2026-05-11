"""
Database Connection Management - Production Grade
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from app.core.config import settings
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

Base = declarative_base()

class DatabaseManager:
    def __init__(self):
        self.engine = None
        self.async_session = None

    async def initialize(self):
        """Initialize database connection"""
        self.engine = create_async_engine(
            settings.database_url,
            echo=False,  # Turn off echo for performance
            pool_size=50,
            max_overflow=100,
            pool_timeout=30,
            pool_recycle=3600,
            pool_pre_ping=True
        )

        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
        logger.info("Database connection initialized")

    async def close(self):
        if self.engine:
            await self.engine.dispose()
            logger.info("Database connection closed")

    def get_session(self):
        return self.async_session()

db_manager = DatabaseManager()

async def get_db():
    """Dependency for getting database session"""
    session = db_manager.get_session()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database session error: {e}")
        await session.rollback()
        raise
    finally:
        await session.close()

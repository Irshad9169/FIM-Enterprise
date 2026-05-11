"""
Whitelist Service - Check if file changes should be suppressed
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Dict, Optional
import re
import logging

logger = logging.getLogger(__name__)

class WhitelistChecker:
    """Check if file changes match whitelist rules"""
    
    @staticmethod
    async def check_file(file_path: str, file_hash: Optional[str], db: AsyncSession) -> Optional[Dict]:
        """
        Check if a file matches any active whitelist rules
        Returns rule info if matched, None otherwise
        NOTE: Does NOT update match counts - that's done separately to avoid transaction issues
        """
        try:
            result = await db.execute(
                text("""
                    SELECT id, rule_name, rule_type, match_value, severity_override, is_temporary, expires_at
                    FROM fim.whitelist_rules
                    WHERE is_active = TRUE
                    AND (is_temporary = FALSE OR expires_at > NOW())
                    ORDER BY rule_type
                """)
            )
            
            rules = result.fetchall()
            
            for rule in rules:
                rule_id, rule_name, rule_type, match_value, severity_override, is_temporary, expires_at = rule
                
                matched = False
                
                if rule_type == 'path' and file_path == match_value:
                    matched = True
                elif rule_type == 'pattern':
                    try:
                        if re.search(match_value, file_path):
                            matched = True
                    except re.error:
                        logger.warning(f"Invalid regex pattern in rule {rule_name}: {match_value}")
                elif rule_type == 'hash' and file_hash and file_hash == match_value:
                    matched = True
                elif rule_type == 'extension':
                    ext = file_path.split('.')[-1] if '.' in file_path else ''
                    if ext == match_value.lstrip('.'):
                        matched = True
                elif rule_type == 'directory' and file_path.startswith(match_value):
                    matched = True
                
                if matched:
                    logger.info(f"File {file_path} matched whitelist rule: {rule_name}")
                    
                    return {
                        'rule_id': str(rule_id),
                        'rule_name': rule_name,
                        'rule_type': rule_type,
                        'severity_override': severity_override,
                        'is_temporary': is_temporary,
                        'expires_at': expires_at.isoformat() if expires_at else None
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Whitelist check failed: {e}")
            return None
    
    @staticmethod
    async def update_match_stats(rule_id: str, db: AsyncSession):
        """Update match statistics for a rule (separate transaction)"""
        try:
            await db.execute(
                text("""
                    UPDATE fim.whitelist_rules
                    SET match_count = match_count + 1,
                        last_matched_at = NOW()
                    WHERE id = :rule_id
                """),
                {'rule_id': rule_id}
            )
        except Exception as e:
            logger.error(f"Failed to update match stats: {e}")
    
    @staticmethod
    async def log_match(rule_id: str, file_path: str, scan_id: Optional[str], 
                       suppressed: bool, db: AsyncSession):
        """Log when a whitelist rule matches"""
        try:
            await db.execute(
                text("""
                    INSERT INTO fim.whitelist_matches 
                    (rule_id, file_path, scan_id, suppressed_alert, details)
                    VALUES (:rule_id, :path, :scan_id, :suppressed, :details::jsonb)
                """),
                {
                    'rule_id': rule_id,
                    'path': file_path,
                    'scan_id': scan_id,
                    'suppressed': suppressed,
                    'details': '{}'
                }
            )
        except Exception as e:
            logger.error(f"Failed to log whitelist match: {e}")
    
    @staticmethod
    async def cleanup_expired_rules(db: AsyncSession) -> int:
        """Remove expired temporary rules"""
        try:
            result = await db.execute(
                text("""
                    DELETE FROM fim.whitelist_rules
                    WHERE is_temporary = TRUE
                    AND expires_at < NOW()
                    RETURNING id
                """)
            )
            
            deleted_count = len(result.fetchall())
            
            if deleted_count > 0:
                await db.commit()
                logger.info(f"Cleaned up {deleted_count} expired whitelist rules")
            
            return deleted_count
        except Exception as e:
            logger.error(f"Failed to cleanup expired rules: {e}")
            return 0

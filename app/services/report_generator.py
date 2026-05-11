"""
Daily Report Generator - With File Hash Details
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, date
import uuid
import json
import logging

logger = logging.getLogger(__name__)

class ReportGenerator:
    
    @staticmethod
    async def generate_daily_report(report_date: date, db: AsyncSession):
        """Generate daily report"""
        
        try:
            report_id = uuid.uuid4()
            start_time = datetime.combine(report_date, datetime.min.time())
            end_time = datetime.combine(report_date, datetime.max.time())
            
            result = await db.execute(text("""
                SELECT COUNT(DISTINCT a.agent_id), COUNT(*)
                FROM fim.alerts a
                WHERE a.detected_at >= :start AND a.detected_at <= :end
            """), {'start': start_time, 'end': end_time})
            
            total_servers, total_changes = result.fetchone()
            
            if total_changes == 0:
                return None
            
            await db.execute(text("""
                INSERT INTO fim.reports 
                (id, report_type, report_date, total_changes, total_servers, status)
                VALUES (:id, 'daily', :date, :changes, :servers, 'pending')
            """), {
                'id': str(report_id),
                'date': report_date,
                'changes': total_changes,
                'servers': total_servers
            })
            
            groups_count = await ReportGenerator._create_detailed_groups(
                report_id, report_date, db
            )
            
            await db.execute(text("""
                UPDATE fim.reports 
                SET correlation_groups_count = :count
                WHERE id = :id
            """), {'id': str(report_id), 'count': groups_count})
            
            await db.commit()
            logger.info(f"✅ Generated report {report_id} with {groups_count} groups")
            return report_id
            
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            await db.rollback()
            raise
    
    @staticmethod
    async def _create_detailed_groups(report_id, report_date, db):
        """Create groups with detailed file change information"""
        
        start_time = datetime.combine(report_date, datetime.min.time())
        end_time = datetime.combine(report_date, datetime.max.time())
        
        result = await db.execute(text("""
            SELECT 
                a.file_path,
                COUNT(*) as change_count,
                COUNT(DISTINCT a.agent_id) as server_count,
                MAX(a.severity) as severity,
                MIN(a.detected_at) as first_seen,
                MAX(a.detected_at) as last_seen
            FROM fim.alerts a
            WHERE a.detected_at >= :start AND a.detected_at <= :end
            GROUP BY a.file_path
            HAVING COUNT(*) >= 2
        """), {'start': start_time, 'end': end_time})
        
        groups = result.fetchall()
        
        for group in groups:
            file_path, change_count, server_count, severity, first_seen, last_seen = group
            group_id = uuid.uuid4()
            
            result = await db.execute(text("""
                SELECT 
                    a.id, a.agent_id, a.severity, a.detected_at, a.alert_type,
                    a.previous_state, a.current_state, a.change_details,
                    COALESCE(ag.hostname, 'unknown') as hostname,
                    ag.ip_address
                FROM fim.alerts a
                LEFT JOIN fim.agents ag ON a.agent_id = ag.id
                WHERE a.file_path = :path
                AND a.detected_at >= :start AND a.detected_at <= :end
                ORDER BY a.detected_at
            """), {'path': file_path, 'start': start_time, 'end': end_time})
            
            alerts = result.fetchall()
            
            hosts = []
            common_changes = {
                'hash_changed': 0,
                'permissions_changed': 0,
                'owner_changed': 0,
                'size_changed': 0
            }
            
            for alert in alerts:
                alert_id, agent_id, sev, det_at, alert_type, prev_state, curr_state, change_details, hostname, ip = alert
                
                prev_hash = prev_state.get('hash') if prev_state else None
                curr_hash = curr_state.get('hash') if curr_state else None
                
                host_data = {
                    "alert_id": str(alert_id),
                    "agent_id": str(agent_id),
                    "hostname": hostname,
                    "ip_address": ip,
                    "severity": sev,
                    "detected_at": det_at.isoformat() if det_at else None,
                    "alert_type": alert_type,
                    "file_changes": {
                        "previous_hash": prev_hash,
                        "current_hash": curr_hash,
                        "previous_size": prev_state.get('size') if prev_state else None,
                        "current_size": curr_state.get('size') if curr_state else None,
                        "previous_permissions": prev_state.get('permissions') if prev_state else None,
                        "current_permissions": curr_state.get('permissions') if curr_state else None,
                        "previous_owner": prev_state.get('owner') if prev_state else None,
                        "current_owner": curr_state.get('owner') if curr_state else None,
                    }
                }
                
                hosts.append(host_data)
                
                if change_details:
                    if change_details.get('hash_changed'):
                        common_changes['hash_changed'] += 1
                    if change_details.get('permissions_changed'):
                        common_changes['permissions_changed'] += 1
                    if change_details.get('owner_changed'):
                        common_changes['owner_changed'] += 1
                    if change_details.get('size_changed'):
                        common_changes['size_changed'] += 1
            
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
                'common_changes': common_changes,
                'time_range': {
                    'start': first_seen.isoformat() if first_seen else None,
                    'end': last_seen.isoformat() if last_seen else None
                }
            })
            
            await db.execute(text("""
                INSERT INTO fim.correlation_groups
                (id, report_id, group_name, group_label, file_pattern, 
                 server_count, change_count, severity, first_seen, last_seen,
                 affected_hosts)
                VALUES 
                (:id, :report_id, :name, :label, :pattern,
                 :servers, :changes, :severity, :first, :last,
                 CAST(:hosts AS jsonb))
            """), {
                'id': str(group_id),
                'report_id': str(report_id),
                'name': file_path.split('/')[-1] if file_path else 'unknown',
                'label': file_path,
                'pattern': file_path,
                'servers': server_count,
                'changes': change_count,
                'severity': severity or 'medium',
                'first': first_seen,
                'last': last_seen,
                'hosts': hosts_json
            })
            
            for alert in alerts:
                await db.execute(text("""
                    INSERT INTO fim.report_changes 
                    (id, report_id, correlation_group_id, alert_id, 
                     agent_hostname, file_path, change_type, severity)
                    VALUES (:id, :rid, :gid, :aid, :host, :path, :type, :sev)
                """), {
                    'id': str(uuid.uuid4()),
                    'rid': str(report_id),
                    'gid': str(group_id),
                    'aid': str(alert[0]),
                    'host': alert[8],
                    'path': file_path,
                    'type': alert[4] or 'modification',
                    'sev': alert[2]
                })
        
        return len(groups)

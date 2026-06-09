"""
Anomaly Detection Service — GAP #19

Three detection engines run hourly:
  1. Alert Volume Spike  — z-score vs 7-day rolling average
  2. Repeated File Mods  — same file changed >5x in 7 days
  3. Combined Score      — 0-100 anomaly score per agent

Usage:
    from app.services.anomaly_detector import run_anomaly_detection
    await run_anomaly_detection(db)
"""

import json
import logging
import statistics
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Thresholds
SPIKE_MULTIPLIER    = 3.0   # today > 3× 7-day avg = spike
SPIKE_MIN_ABSOLUTE  = 20    # must also exceed 20 alerts (not just 3× of 2)
REPEAT_THRESHOLD    = 5     # same file modified >5× in 7 days = suspicious
MIN_HISTORY_DAYS    = 3     # need at least 3 days of history to detect spikes


async def run_anomaly_detection(db: AsyncSession) -> List[Dict]:
    """
    Run all anomaly detection engines for all agents.
    Stores results in fim.anomaly_scores.
    Returns list of anomalous agents (score > 30).
    """
    logger.info("GAP#19: Starting anomaly detection run")
    anomalies = []

    try:
        # Get all active agents
        agents_result = await db.execute(text("""
            SELECT id, hostname
            FROM fim.agents
            WHERE status = 'active' OR last_seen > NOW() - INTERVAL '24 hours'
        """))
        agents = agents_result.fetchall()

        for agent in agents:
            try:
                score_data = await _analyze_agent(db, agent.id, agent.hostname)
                await _store_score(db, agent.id, score_data)

                if score_data["score"] > 30:
                    anomalies.append({
                        "agent_id":  str(agent.id),
                        "hostname":  agent.hostname,
                        **score_data,
                    })
                    logger.warning(
                        "GAP#19: Anomaly detected | agent=%s score=%d "
                        "level=%s summary=%s",
                        agent.hostname, score_data["score"],
                        score_data["level"], score_data["summary"]
                    )
            except Exception as e:
                logger.error("GAP#19: Error analyzing agent %s: %s",
                             agent.hostname, e)

        await db.commit()
        logger.info("GAP#19: Detection complete — %d anomalies found",
                    len(anomalies))
        return anomalies

    except Exception as e:
        logger.error("GAP#19: Detection run failed: %s", e)
        return []


async def _analyze_agent(db: AsyncSession,
                          agent_id: Any,
                          hostname: str) -> dict:
    """Run all engines for one agent and return combined score."""
    now = datetime.now(timezone.utc)

    # ── Engine 1: Alert Volume Spike ─────────────────────────────
    # Get daily alert counts for last 8 days
    volume_result = await db.execute(text("""
        SELECT
            DATE(created_at AT TIME ZONE 'UTC') as day,
            COUNT(*) as alert_count
        FROM fim.alerts
        WHERE agent_id = :agent_id
          AND created_at >= NOW() - INTERVAL '8 days'
        GROUP BY DATE(created_at AT TIME ZONE 'UTC')
        ORDER BY day ASC
    """), {"agent_id": str(agent_id)})
    volume_rows = volume_result.fetchall()

    daily_counts = {str(r.day): int(r.alert_count) for r in volume_rows}
    today_str = now.strftime("%Y-%m-%d")
    today_count = daily_counts.get(today_str, 0)

    # 7-day history (excluding today)
    history = [
        v for k, v in daily_counts.items()
        if k != today_str
    ]

    volume_spike = False
    z_score = 0.0
    avg_7d = 0.0

    if len(history) >= MIN_HISTORY_DAYS:
        avg_7d = statistics.mean(history)
        std_7d = statistics.stdev(history) if len(history) > 1 else 1.0
        z_score = (today_count - avg_7d) / (std_7d + 0.1)
        volume_spike = (
            today_count > avg_7d * SPIKE_MULTIPLIER
            and today_count > SPIKE_MIN_ABSOLUTE
        )

    # ── Engine 2: Repeated File Modifications ────────────────────
    repeat_result = await db.execute(text("""
        SELECT
            file_path,
            COUNT(*) as modification_count
        FROM fim.alerts
        WHERE agent_id = :agent_id
          AND created_at >= NOW() - INTERVAL '7 days'
          AND file_path IS NOT NULL
        GROUP BY file_path
        HAVING COUNT(*) >= :threshold
        ORDER BY modification_count DESC
        LIMIT 20
    """), {"agent_id": str(agent_id), "threshold": REPEAT_THRESHOLD})
    repeat_rows = repeat_result.fetchall()

    repeated_files = len(repeat_rows)
    repeat_details = [
        {"path": r.file_path, "count": int(r.modification_count)}
        for r in repeat_rows
    ]

    # ── Engine 3: Compute Combined Score (0-100) ─────────────────
    score = 0

    # Volume spike contribution (0-50 points)
    if volume_spike:
        spike_points = min(50, int(abs(z_score) * 5))
        score += spike_points

    # Repeated files contribution (0-40 points)
    if repeated_files > 0:
        repeat_points = min(40, repeated_files * 8)
        score += repeat_points

    # Bonus: both engines fired simultaneously (10 points)
    if volume_spike and repeated_files > 0:
        score = min(100, score + 10)

    score = min(100, score)

    # Determine level
    if score >= 80:
        level = "critical"
    elif score >= 60:
        level = "high"
    elif score >= 30:
        level = "medium"
    else:
        level = "low"

    # Build summary message
    parts = []
    if volume_spike:
        parts.append(
            f"Alert spike: {today_count} alerts today "
            f"(avg {avg_7d:.1f}/day, z={z_score:.1f})"
        )
    if repeated_files > 0:
        top = repeat_details[0]
        parts.append(
            f"{repeated_files} file(s) modified >{REPEAT_THRESHOLD}× "
            f"in 7 days (top: {top['path']} × {top['count']})"
        )
    summary = " | ".join(parts) if parts else "No anomalies detected"

    return {
        "score":          score,
        "level":          level,
        "alerts_today":   today_count,
        "alerts_avg_7d":  round(avg_7d, 2),
        "z_score":        round(z_score, 2),
        "volume_spike":   volume_spike,
        "repeated_files": repeated_files,
        "repeat_details": repeat_details,
        "summary":        summary,
    }


async def _store_score(db: AsyncSession,
                        agent_id: Any, data: dict) -> None:
    """Upsert anomaly score for this agent."""
    await db.execute(text("""
        INSERT INTO fim.anomaly_scores (
            agent_id, computed_at, score, level,
            alerts_today, alerts_avg_7d, z_score, volume_spike,
            repeated_files, repeat_details, summary
        ) VALUES (
            :agent_id, NOW(), :score, :level,
            :alerts_today, :alerts_avg_7d, :z_score, :volume_spike,
            :repeated_files, :repeat_details, :summary
        )
        ON CONFLICT (agent_id, computed_at)
        DO UPDATE SET
            score          = EXCLUDED.score,
            level          = EXCLUDED.level,
            alerts_today   = EXCLUDED.alerts_today,
            alerts_avg_7d  = EXCLUDED.alerts_avg_7d,
            z_score        = EXCLUDED.z_score,
            volume_spike   = EXCLUDED.volume_spike,
            repeated_files = EXCLUDED.repeated_files,
            repeat_details = EXCLUDED.repeat_details,
            summary        = EXCLUDED.summary
    """), {
        "agent_id":       str(agent_id),
        "score":          data["score"],
        "level":          data["level"],
        "alerts_today":   data["alerts_today"],
        "alerts_avg_7d":  data["alerts_avg_7d"],
        "z_score":        data["z_score"],
        "volume_spike":   data["volume_spike"],
        "repeated_files": data["repeated_files"],
        "repeat_details": json.dumps(data["repeat_details"]),
        "summary":        data["summary"],
    })


async def get_latest_anomaly_scores(db: AsyncSession) -> List[Dict]:
    """
    Return the most recent anomaly score per agent.
    Used by the dashboard widget and API endpoint.
    """
    result = await db.execute(text("""
        SELECT DISTINCT ON (s.agent_id)
            s.agent_id,
            a.hostname,
            s.score,
            s.level,
            s.alerts_today,
            s.alerts_avg_7d,
            s.z_score,
            s.volume_spike,
            s.repeated_files,
            s.repeat_details,
            s.summary,
            s.computed_at
        FROM fim.anomaly_scores s
        JOIN fim.agents a ON s.agent_id = a.id
        ORDER BY s.agent_id, s.computed_at DESC
    """))
    rows = result.fetchall()
    return [
        {
            "agent_id":       str(r.agent_id),
            "hostname":       r.hostname,
            "score":          r.score,
            "level":          r.level,
            "alerts_today":   r.alerts_today,
            "alerts_avg_7d":  float(r.alerts_avg_7d),
            "z_score":        float(r.z_score),
            "volume_spike":   r.volume_spike,
            "repeated_files": r.repeated_files,
            "repeat_details": r.repeat_details or [],
            "summary":        r.summary,
            "computed_at":    str(r.computed_at),
        }
        for r in rows
    ]

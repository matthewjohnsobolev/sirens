"""
Load and activity metrics collector for Sirens Operations (sirens-ops).
Gathers sent message stats, host CPU & RAM, Docker container stats, and service health.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
from typing import Any

from ops.state import get_pg_connection, get_redis_client

log = logging.getLogger(__name__)


def _get_pg_conn():
    try:
        import psycopg2

        from config import DATABASE_URL

        return psycopg2.connect(DATABASE_URL, connect_timeout=3)
    except Exception:
        return get_pg_connection()


def _get_redis_client():
    try:
        import redis

        from config import REDIS_URL

        return redis.from_url(
            REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
    except Exception:
        return get_redis_client()


def format_bytes(n: int | float | None) -> str:
    """Format bytes into human-readable string (e.g. 1.45 GB, 250 MB)."""
    if n is None:
        return "N/A"
    val = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(val) < 1024.0:
            if unit in ["MB", "GB", "TB"]:
                return f"{val:.2f} {unit}"
            return f"{int(val)} {unit}"
        val /= 1024.0
    return f"{val:.2f} PB"


def get_message_metrics(pg_conn=None, pg_error=None) -> dict[str, Any]:
    """Query message volume from PostgreSQL alert_history over the last 24 hours and today."""
    if pg_error:
        return {"error": f"Failed to connect to PostgreSQL: {pg_error}"}

    conn = pg_conn
    owns_conn = False
    if conn is None:
        try:
            conn = _get_pg_conn()
            owns_conn = True
        except Exception as e:
            return {"error": f"Failed to connect to PostgreSQL: {e}"}

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours') AS broadcast_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND type = 'air_raid_alert') AS alert_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND type = 'air_raid_alert_cancelled') AS alert_cancel_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND type = 'threat_of_shelling') AS shelling_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND type = 'threat_of_shelling_cancelled') AS shelling_cancel_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND (message_link LIKE '%t.me/%' OR message_link LIKE '%telegram%')) AS auto_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND datetime >= NOW() - INTERVAL '24 hours' AND (message_link NOT LIKE '%t.me/%' AND (message_link NOT LIKE '%telegram%' OR message_link IS NULL))) AS manual_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NULL AND datetime >= NOW() - INTERVAL '24 hours') AS map_only_24h,
                    COUNT(*) FILTER (WHERE datetime >= NOW() - INTERVAL '24 hours') AS total_events_24h,
                    COUNT(*) FILTER (WHERE channel_id IS NOT NULL AND date = CURRENT_DATE) AS broadcast_today,
                    COUNT(*) FILTER (WHERE channel_id IS NULL AND date = CURRENT_DATE) AS map_only_today,
                    COUNT(*) FILTER (WHERE date = CURRENT_DATE) AS total_events_today
                FROM alert_history
                WHERE datetime >= NOW() - INTERVAL '24 hours' OR date = CURRENT_DATE;
                """
            )
            row = cur.fetchone()
            if not row:
                return {"error": "No data returned from alert_history"}

            return {
                "broadcast_24h": row[0] or 0,
                "alert_24h": row[1] or 0,
                "alert_cancel_24h": row[2] or 0,
                "shelling_24h": row[3] or 0,
                "shelling_cancel_24h": row[4] or 0,
                "auto_24h": row[5] or 0,
                "manual_24h": row[6] or 0,
                "map_only_24h": row[7] or 0,
                "total_events_24h": row[8] or 0,
                "broadcast_today": row[9] or 0,
                "map_only_today": row[10] or 0,
                "total_events_today": row[11] or 0,
                "error": None,
            }
    except Exception as e:
        return {"error": f"Failed to query alert_history: {e}"}
    finally:
        if owns_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _fallback_system_metrics() -> dict[str, Any]:
    """Fallback Linux system stats if psutil is unavailable."""
    res: dict[str, Any] = {
        "cpu_percent": None,
        "load_avg": None,
        "cpu_count": os.cpu_count() or 1,
        "ram": None,
        "swap": None,
        "source": "fallback",
    }
    if hasattr(os, "getloadavg"):
        try:
            res["load_avg"] = os.getloadavg()
        except Exception:
            pass

    # Read /proc/meminfo on Linux
    if os.path.exists("/proc/meminfo"):
        try:
            meminfo: dict[str, int] = {}
            with open("/proc/meminfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().split()[0]
                        if v.isdigit():
                            meminfo[k] = int(v) * 1024  # kB to bytes
            total = meminfo.get("MemTotal", 0)
            avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            if total > 0:
                used = total - avail
                res["ram"] = {
                    "total": total,
                    "used": used,
                    "available": avail,
                    "percent": round((used / total) * 100, 1),
                }
            sw_total = meminfo.get("SwapTotal", 0)
            sw_free = meminfo.get("SwapFree", 0)
            if sw_total > 0:
                sw_used = sw_total - sw_free
                res["swap"] = {
                    "total": sw_total,
                    "used": sw_used,
                    "free": sw_free,
                    "percent": round((sw_used / sw_total) * 100, 1),
                }
        except Exception:
            pass

    return res


def get_system_metrics() -> dict[str, Any]:
    """Collect host CPU load, load average, and RAM memory usage."""
    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)
        load_avg = None
        if hasattr(psutil, "getloadavg"):
            try:
                load_avg = psutil.getloadavg()
            except Exception:
                pass
        if not load_avg and hasattr(os, "getloadavg"):
            try:
                load_avg = os.getloadavg()
            except Exception:
                pass

        vm = psutil.virtual_memory()
        ram = {
            "total": vm.total,
            "used": vm.used,
            "available": vm.available,
            "percent": vm.percent,
        }

        swap = None
        try:
            sw = psutil.swap_memory()
            if sw.total > 0:
                swap = {
                    "total": sw.total,
                    "used": sw.used,
                    "free": sw.free,
                    "percent": sw.percent,
                }
        except Exception:
            pass

        return {
            "cpu_percent": cpu_percent,
            "load_avg": load_avg,
            "cpu_count": psutil.cpu_count(logical=True) or 1,
            "ram": ram,
            "swap": swap,
            "source": "psutil",
            "error": None,
        }
    except ImportError:
        fb = _fallback_system_metrics()
        fb["error"] = None
        return fb
    except Exception as e:
        fb = _fallback_system_metrics()
        fb["error"] = f"Error reading system metrics: {e}"
        return fb


def get_container_metrics(timeout_sec: float = 1.0) -> list[dict[str, Any]]:
    """Collect CPU & RAM usage for Sirens Docker containers using docker stats CLI if available."""
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return []

    try:
        proc = subprocess.run(
            [
                docker_bin,
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode != 0:
            return []

        containers = []
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 4:
                c_name = parts[0].strip()
                if "sirens" in c_name.lower():
                    containers.append(
                        {
                            "name": c_name,
                            "cpu": parts[1].strip(),
                            "mem_usage": parts[2].strip(),
                            "mem_percent": parts[3].strip(),
                        }
                    )
        return containers
    except Exception:
        return []


def get_service_metrics(
    redis_client=None, pg_conn=None, redis_error=None, pg_error=None
) -> dict[str, Any]:
    """Collect internal health and memory usage of Redis and PostgreSQL."""
    services: dict[str, Any] = {
        "redis": None,
        "postgres": None,
    }

    # 1. Redis metrics
    if redis_error:
        services["redis"] = {"error": str(redis_error)}
    else:
        r_client = redis_client
        if r_client is None:
            try:
                r_client = _get_redis_client()
            except Exception as e:
                services["redis"] = {"error": str(e)}

        if r_client is not None and services["redis"] is None:
            try:
                info_mem = r_client.info("memory")
                info_clients = r_client.info("clients")
                services["redis"] = {
                    "used_memory_human": info_mem.get("used_memory_human", "N/A"),
                    "used_memory_peak_human": info_mem.get("used_memory_peak_human", "N/A"),
                    "connected_clients": info_clients.get("connected_clients", 0),
                    "error": None,
                }
            except Exception as e:
                services["redis"] = {"error": str(e)}

    # 2. PostgreSQL metrics
    if pg_error:
        services["postgres"] = {"error": str(pg_error)}
    else:
        p_conn = pg_conn
        owns_conn = False
        if p_conn is None:
            try:
                p_conn = _get_pg_conn()
                owns_conn = True
            except Exception as e:
                services["postgres"] = {"error": str(e)}

        if p_conn is not None and services["postgres"] is None:
            try:
                with p_conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT current_database(),
                               pg_size_pretty(pg_database_size(current_database())),
                               (SELECT count(*) FROM pg_stat_activity);
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        services["postgres"] = {
                            "database": row[0],
                            "size": row[1],
                            "connections": row[2],
                            "error": None,
                        }
            except Exception as e:
                services["postgres"] = {"error": str(e)}
            finally:
                if owns_conn:
                    try:
                        p_conn.close()
                    except Exception:
                        pass

    return services


def collect_all_metrics(pg_conn=None, redis_client=None) -> dict[str, Any]:
    """Aggregate all operational load metrics sharing open connections where possible."""
    conn = pg_conn
    owns_conn = False
    pg_err = None
    if conn is None:
        try:
            conn = _get_pg_conn()
            owns_conn = True
        except Exception as e:
            pg_err = str(e)

    r_client = redis_client
    redis_err = None
    if r_client is None:
        try:
            r_client = _get_redis_client()
        except Exception as e:
            redis_err = str(e)

    try:
        return {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "messages": get_message_metrics(pg_conn=conn, pg_error=pg_err),
            "system": get_system_metrics(),
            "containers": get_container_metrics(),
            "services": get_service_metrics(
                redis_client=r_client,
                pg_conn=conn,
                redis_error=redis_err,
                pg_error=pg_err,
            ),
        }
    finally:
        if owns_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass

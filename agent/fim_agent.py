#!/usr/bin/env python3
"""
FIM Agent - File Integrity Monitoring Client
"""
import os
import sys
import time
import json
import yaml
import hashlib
import hmac
import fnmatch
import logging
import platform
import socket
import threading
import subprocess
import re
import requests
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

# Real-time filesystem watching (complements the scheduled full scan — see
# FIMAgent._check_realtime_trigger). Optional dependency: if watchdog isn't
# installed, the agent falls back to scheduled-scan-only, same as before.
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

# ── GAP #11 / Agent 413 Fix: chunked scan submission ────────────
SCAN_CHUNK_SIZE = 10_000   # max files per API call
MAX_PAYLOAD_BYTES = 45_000_000  # 45MB safety margin (server allows 50MB)

def _send_chunked(session, url, headers, agent_id, scan_type,
                  files_data, scan_metadata):
    """
    Split large scan results into chunks and submit each separately.
    Prevents 413 errors when monitoring paths with many files.
    """
    import math, json

    total_files = len(files_data)
    if total_files == 0:
        return _send_single(session, url, headers, agent_id,
                            scan_type, [], scan_metadata)

    # Estimate payload size
    sample = json.dumps(files_data[:min(100, total_files)])
    avg_bytes = len(sample) / min(100, total_files)
    estimated_total = avg_bytes * total_files

    # If small enough, send as single request
    if estimated_total < MAX_PAYLOAD_BYTES and total_files <= SCAN_CHUNK_SIZE:
        return _send_single(session, url, headers, agent_id,
                            scan_type, files_data, scan_metadata)

    # Split into chunks
    num_chunks = math.ceil(total_files / SCAN_CHUNK_SIZE)
    logging.info(
        f"Large scan: {total_files} files ~{estimated_total/1_000_000:.1f}MB "
        f"→ splitting into {num_chunks} chunks of {SCAN_CHUNK_SIZE}"
    )

    results = []
    for i in range(num_chunks):
        chunk = files_data[i * SCAN_CHUNK_SIZE:(i + 1) * SCAN_CHUNK_SIZE]
        chunk_meta = {
            **scan_metadata,
            "chunk_index": i,
            "chunk_total": num_chunks,
            "is_partial": True,
        }
        logging.info(f"Sending chunk {i+1}/{num_chunks} ({len(chunk)} files)")
        result = _send_single(session, url, headers, agent_id,
                              scan_type, chunk, chunk_meta)
        results.append(result)

    return results[-1] if results else None


def _send_single(session, url, headers, agent_id, scan_type,
                 files_data, scan_metadata):
    """Send a single scan payload to the server."""
    import json
    payload = {
        "agent_id": agent_id,
        "scan_type": scan_type,
        "files": files_data,
        **scan_metadata,
    }
    payload_bytes = len(json.dumps(payload))
    logging.debug(f"Sending scan payload: {payload_bytes:,} bytes, "
                  f"{len(files_data)} files")
    response = session.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    return response

# ── End chunked scan helper ──────────────────────────────────────

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('FIMAgent')

class AgentConfig:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with open(self.config_path, 'r') as f:
            return yaml.safe_load(f)

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def __getitem__(self, key):
        return self.config[key]

class FIMClient:
    def __init__(self, server_url: str, api_key: str):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'X-API-Key': api_key,
            'Content-Type': 'application/json'
        })
        self.logger = logging.getLogger('FIMAgent.Client')

    def register_agent(self, hostname: str, ip_address: str) -> Optional[str]:
        """Register agent with server"""
        try:
            data = {
                'hostname': hostname,
                'ip_address': ip_address,
                'os_type': platform.system(),
                'os_version': platform.release(),
                'agent_version': '1.0.0'
            }

            response = self.session.post(
                f'{self.server_url}/api/v1/agents/register',
                json=data,
                timeout=10
            )
            response.raise_for_status()

            result = response.json()
            # Handle both id and agent_id formats
            agent_id = result.get('agent_id') or result.get('id')
            self.logger.info(f"Agent registered: {agent_id}")
            return agent_id

        except Exception as e:
            self.logger.error(f"Registration failed: {e}")
            return None

    def send_heartbeat(self, agent_id: str, hostname: str):
        """Send heartbeat to server"""
        try:
            data = {
                'agent_id': agent_id,
                'hostname': hostname,
                'timestamp': datetime.utcnow().isoformat()
            }

            response = self.session.post(
                f'{self.server_url}/api/v1/agents/heartbeat',
                json=data,
                timeout=10
            )
            response.raise_for_status()
            
            # Check for on-demand scan
            try:
                resp_data = response.json()
                if isinstance(resp_data, dict) and resp_data.get('scan_required'):
                    self.logger.info("Received on-demand scan request from server")
                    return "SCAN_REQUIRED"
            except Exception as json_err:
                self.logger.warning(f"Failed to parse heartbeat response: {json_err}")

            self.logger.debug("Heartbeat sent")
            return True

        except Exception as e:
            self.logger.error(f"Heartbeat failed: {e}")
            return False

    def send_scan_results(self, agent_id: str, scan_data: List[Dict], scan_type: str = 'full'):
        """Send scan results to server"""
        try:
            data = {
                'agent_id': agent_id,
                'files': scan_data,
                'timestamp': datetime.utcnow().isoformat(),
                'total_files': len(scan_data),
                'scan_type': scan_type
            }

            # Sign payload with HMAC-SHA256
            canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
            sig = 'hmac-sha256=' + hmac.new(
                self.api_key.encode('utf-8'),
                canonical.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            response = self.session.post(
                f'{self.server_url}/api/v1/scans/submit',
                json=data,
                headers={'X-Scan-Signature': sig},
                timeout=30
            )
            response.raise_for_status()
            self.logger.info(f"Scan results sent: {len(scan_data)} files (signed)")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send scan results: {e}")
            return False

class FileScanner:
    def __init__(self, paths: List[Union[str, Dict]], hash_algo: str = 'sha256',
                 cache_path: Optional[str] = None,
                 audit_critical_paths: Optional[set] = None):
        # Normalize paths: each monitored path keeps its own exclude_patterns
        # (config['monitoring']['paths'] entries look like
        #  {path: /opt, recursive: true, exclude_patterns: [...]}).
        # Previously only 'path' was ever read here — exclude_patterns was
        # silently dropped, so every exclusion entry in agent_config.yaml
        # (fim*, IBM*, EMPsysedge*, etc.) had zero effect on what got scanned.
        self.path_configs = []
        for p in paths:
            if isinstance(p, dict):
                self.path_configs.append({
                    'path': p.get('path'),
                    'exclude_patterns': p.get('exclude_patterns') or [],
                })
            else:
                self.path_configs.append({'path': str(p), 'exclude_patterns': []})

        self.hash_algo = hash_algo
        self.logger = logging.getLogger('FIMAgent.Scanner')

        # Incremental scanning: skip re-hashing files whose mtime+size are
        # unchanged since the last scan, instead of hashing every monitored
        # file every cycle. Every file is still reported every cycle (the
        # outgoing payload shape is unchanged) — this only avoids the
        # read-and-hash work for files that provably didn't change.
        self.cache_path = cache_path
        self._prev_cache: Dict[str, Dict] = self._load_cache()
        self._new_cache: Dict[str, Dict] = {}
        self.hashes_skipped = 0
        self.hashes_computed = 0

        # auditd correlation: curated critical-path list only (not the whole
        # monitored tree — auditd has a rule-count limit and blanket watches
        # over tens of thousands of files would be both infeasible and
        # noisy). Only correlates when a critical file's content actually
        # changed since our own last scan (see _process_file) — not on
        # first sight, and not for every scan of an unchanged file.
        self.audit_critical_paths = set(audit_critical_paths or [])

    def _load_cache(self) -> Dict[str, Dict]:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load scan cache, starting fresh: {e}")
            return {}

    def _save_cache(self):
        if not self.cache_path:
            return
        try:
            tmp_path = self.cache_path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(self._new_cache, f)
            os.replace(tmp_path, self.cache_path)
            try:
                os.chmod(self.cache_path, 0o600)
            except Exception:
                pass  # not meaningful on all platforms (e.g. Windows) — best effort
        except Exception as e:
            self.logger.warning(f"Failed to persist scan cache: {e}")

    def calculate_hash(self, file_path: str) -> str:
        """Calculate file hash"""
        try:
            hash_func = getattr(hashlib, self.hash_algo)()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_func.update(chunk)
            return hash_func.hexdigest()
        except Exception as e:
            self.logger.warning(f"Failed to hash {file_path}: {e}")
            return ""

    @staticmethod
    def _is_excluded(file_path: str, base_path: str, exclude_patterns: List[str]) -> bool:
        """
        Check file_path against exclude_patterns (glob-style), scoped to
        base_path. Matches every path-suffix below base_path, not just the
        full relative path or the bare filename, so a pattern works
        regardless of how deep the match is nested:
          - 'IBM*'          matches a component named IBM, IBM-something, ... anywhere
          - '__pycache__/*' matches anything inside any __pycache__ dir, any depth
          - '*.tmp'         matches any file ending in .tmp, any depth
        """
        if not exclude_patterns:
            return False
        try:
            rel_path = os.path.relpath(file_path, base_path)
        except ValueError:
            rel_path = file_path
        parts = rel_path.split(os.sep)
        suffixes = [os.sep.join(parts[i:]) for i in range(len(parts))]
        return any(
            fnmatch.fnmatch(suffix, pattern)
            for pattern in exclude_patterns
            for suffix in suffixes
        )

    def scan(self) -> List[Dict]:
        """Scan all monitored paths, honoring each path's own exclude_patterns"""
        results = []
        self.logger.info(f"Starting scan of {len(self.path_configs)} paths")
        # Rebuilt fresh each cycle (not merged) so files that no longer exist
        # don't linger in the cache forever.
        self._new_cache = {}
        self.hashes_skipped = 0
        self.hashes_computed = 0

        for path_config in self.path_configs:
            path = path_config['path']
            exclude_patterns = path_config['exclude_patterns']

            if not path or not os.path.exists(path):
                self.logger.warning(f"Path not found: {path}")
                continue

            if os.path.isfile(path):
                if self._is_excluded(path, path, exclude_patterns):
                    continue
                file_info = self._process_file(path)
                if file_info:
                    results.append(file_info)
            else:
                for root, dirs, files in os.walk(path):
                    # Prune excluded directories in place so os.walk never
                    # descends into them at all (not just filters after the
                    # fact) — this is what actually stops /opt/IBM/* from
                    # being scanned, instead of just discarding the results.
                    dirs[:] = [
                        d for d in dirs
                        if not self._is_excluded(os.path.join(root, d), path, exclude_patterns)
                    ]
                    for file in files:
                        file_path = os.path.join(root, file)
                        if self._is_excluded(file_path, path, exclude_patterns):
                            continue
                        file_info = self._process_file(file_path)
                        if file_info:
                            results.append(file_info)

        self._save_cache()
        self.logger.info(
            f"Scan complete: {len(results)} files scanned "
            f"({self.hashes_computed} hashed, {self.hashes_skipped} unchanged/skipped)"
        )
        return results

    def _process_file(self, file_path: str) -> Optional[Dict]:
        try:
            stat = os.stat(file_path)
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()

            cached = self._prev_cache.get(file_path)
            audit_info = None
            if cached and cached.get('mtime') == mtime and cached.get('size') == size:
                file_hash = cached['hash']
                self.hashes_skipped += 1
            else:
                file_hash = self.calculate_hash(file_path)
                self.hashes_computed += 1
                # Only correlate for a real, locally-detected content change
                # on a critical path — not the first time we've ever seen
                # this file (no local baseline to compare against yet).
                if (file_path in self.audit_critical_paths
                        and cached and cached.get('hash') != file_hash):
                    audit_info = self._correlate_auditd(file_path)

            self._new_cache[file_path] = {'mtime': mtime, 'size': size, 'hash': file_hash}

            result = {
                'path': file_path,
                'hash': file_hash,
                'size': size,
                'mtime': mtime,
                'permissions': oct(stat.st_mode)[-3:],
                'owner': stat.st_uid,
                'group': stat.st_gid
            }
            if audit_info:
                result.update(audit_info)
            return result
        except Exception as e:
            self.logger.warning(f"Error processing {file_path}: {e}")
            return None

    def _correlate_auditd(self, file_path: str) -> Optional[Dict]:
        """
        Best-effort auditd correlation for a critical-path file that just
        changed — who/what process touched it, via `ausearch` (requires
        auditd installed/running and an `auditctl -w <path> -k fim_watch`
        rule already provisioned for this path; see
        docs/PRODUCTION_DEPLOYMENT.md). Returns None silently on anything
        going wrong (auditd absent, no permission, no match in the time
        window) — this must never block or fail a scan, it's purely
        additive metadata.
        """
        try:
            result = subprocess.run(
                ['ausearch', '-k', 'fim_watch', '-f', file_path, '-ts', 'recent', '-i'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            auid = exe = comm = None
            for line in reversed(result.stdout.splitlines()):
                if auid is None:
                    m = re.search(r'\bauid=(\S+)', line)
                    if m and m.group(1) != 'unset':
                        auid = m.group(1)
                if exe is None:
                    m = re.search(r'\bexe="?([^"\s]+)"?', line)
                    if m:
                        exe = m.group(1)
                if comm is None:
                    m = re.search(r'\bcomm="?([^"\s]+)"?', line)
                    if m:
                        comm = m.group(1)
                if auid and exe and comm:
                    break

            if not (auid or exe or comm):
                return None
            return {'audit_uid': auid, 'audit_process': exe, 'audit_command': comm}
        except FileNotFoundError:
            return None  # ausearch not installed — auditd absent, silently skip
        except Exception as e:
            self.logger.warning(f"auditd correlation failed for {file_path}: {e}")
            return None

class _RealtimeChangeHandler(FileSystemEventHandler):
    """
    watchdog event handler for one monitored root. Doesn't scan or hash
    anything itself — just marks the agent "dirty" so the heartbeat loop's
    debounce check (FIMAgent._check_realtime_trigger) can trigger a full
    rescan shortly after activity quiets down. Kept deliberately dumb: the
    existing full-scan/ChangeDetector pipeline already does the real work,
    and it assumes a complete file inventory per submission (see
    ChangeDetector._compare_files) — a partial/per-event submission would
    make every other file look "deleted", so real-time here means "detect
    fast, then trigger the same full pipeline sooner," not "stream deltas."
    """
    def __init__(self, base_path: str, exclude_patterns: List[str], mark_dirty):
        self.base_path = base_path
        self.exclude_patterns = exclude_patterns
        self.mark_dirty = mark_dirty

    def on_any_event(self, event):
        if event.is_directory:
            return
        if FileScanner._is_excluded(event.src_path, self.base_path, self.exclude_patterns):
            return
        self.mark_dirty()


class FIMAgent:
    def __init__(self, config_file: str):
        self.config_path = config_file
        self.logger = logging.getLogger('FIMAgent')
        self.config = AgentConfig(config_file)
        
        # Load paths from config
        self.monitored_paths = self.config['monitoring'].get('paths') or self.config['monitoring'].get('watch_paths')
        if not self.monitored_paths:
            raise ValueError("No monitoring paths defined in config")

        self.client = FIMClient(
            self.config['server']['url'],
            self.config['server']['api_key']
        )
        
        cache_path = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), '.scan_cache.json'
        )
        self.scanner = FileScanner(
            self.monitored_paths,
            self.config['monitoring'].get('hash_algorithm', 'sha256'),
            cache_path=cache_path,
            audit_critical_paths=self.config['monitoring'].get('audit_critical_paths'),
        )
        
        self.hostname = socket.gethostname()
        self.ip_address = socket.gethostbyname(self.hostname)
        self.agent_id = self.config['agent'].get('id')
        self.running = True

        # Real-time watching state — additive to the scheduled scan, not a
        # replacement (see _RealtimeChangeHandler docstring). scan_lock
        # prevents a realtime-triggered scan from overlapping a scheduled one.
        self._scan_lock = threading.Lock()
        self._realtime_lock = threading.Lock()
        self._realtime_pending = False
        self._realtime_last_event = 0.0
        self._realtime_debounce_seconds = self.config['monitoring'].get(
            'realtime_debounce_seconds', 3
        )
        self._observer = None

    def start_realtime_watch(self):
        """
        Start watching monitored directories for filesystem events. Purely
        additive — if watchdog isn't installed, or a given root can't be
        watched (e.g. permission denied, inotify watch limit reached), logs
        a warning and the agent continues on scheduled scans alone.
        """
        if not WATCHDOG_AVAILABLE:
            self.logger.warning(
                "watchdog not installed — real-time detection disabled, "
                "falling back to scheduled scans only"
            )
            return

        observer = Observer()
        watched_count = 0
        for path_config in self.scanner.path_configs:
            path = path_config['path']
            if not path or not os.path.isdir(path):
                continue  # single-file paths: covered by scheduled scan only
            try:
                handler = _RealtimeChangeHandler(
                    path, path_config['exclude_patterns'], self._mark_realtime_dirty
                )
                observer.schedule(handler, path, recursive=True)
                watched_count += 1
            except Exception as e:
                self.logger.warning(f"Real-time watch failed for {path}: {e}")

        if watched_count == 0:
            self.logger.warning("No paths could be watched in real-time")
            return

        observer.start()
        self._observer = observer
        self.logger.info(f"Real-time watching started on {watched_count} path(s)")

    def _mark_realtime_dirty(self):
        with self._realtime_lock:
            self._realtime_pending = True
            self._realtime_last_event = time.time()

    def _check_realtime_trigger(self) -> bool:
        """
        Called periodically from the heartbeat loop. Returns True if a
        realtime-triggered scan was run. Waits for a quiet period after the
        last event (debounce) so a burst of writes to the same file doesn't
        trigger a rescan per-event.
        """
        with self._realtime_lock:
            if not self._realtime_pending:
                return False
            if time.time() - self._realtime_last_event < self._realtime_debounce_seconds:
                return False
            self._realtime_pending = False

        self.logger.info("Real-time change detected — triggering rescan")
        self.run_scan(scan_type='realtime')
        return True

    def register(self):
        """Register agent with server"""
        self.logger.info("Registering agent...")
        self.agent_id = self.client.register_agent(self.hostname, self.ip_address)
        
        if self.agent_id:
            # Save agent_id to config
            self.save_agent_id(self.agent_id)
            return True
        return False

    def save_agent_id(self, agent_id: str):
        """Save agent ID to config file"""
        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        if 'agent' not in config:
            config['agent'] = {}
        config['agent']['id'] = agent_id
        
        with open(self.config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        self.logger.info(f"Agent ID saved: {agent_id}")

    def run_scan(self, scan_type: str = 'full'):
        """Execute file integrity scan"""
        with self._scan_lock:
            self.logger.info(f"Starting file integrity scan (scan_type={scan_type})")
            scan_results = self.scanner.scan()
            if scan_results:
                self.client.send_scan_results(self.agent_id, scan_results, scan_type=scan_type)

    def run_daemon(self):
        """Main agent loop"""
        if not self.agent_id:
            if not self.register():
                self.logger.error("Failed to register agent. Exiting.")
                return

        self.logger.info("Starting heartbeat loop")
        self.logger.info("============================================================")

        # Initial scan
        self.run_scan()
        self.start_realtime_watch()

        last_scan = time.time()
        scan_interval = self.config['monitoring'].get('scan_interval', 3600)
        heartbeat_interval = self.config['monitoring'].get('heartbeat_interval', 60)

        while self.running:
            try:
                # Heartbeat
                result = self.client.send_heartbeat(self.agent_id, self.hostname)

                # Check if scan requested
                if result == "SCAN_REQUIRED":
                    self.run_scan()
                    last_scan = time.time()  # Reset scheduled scan timer

                # Scheduled scan
                if time.time() - last_scan > scan_interval:
                    self.run_scan()
                    last_scan = time.time()

                # Real-time-triggered scan (debounced filesystem events)
                if self._check_realtime_trigger():
                    last_scan = time.time()

                time.sleep(heartbeat_interval)

            except KeyboardInterrupt:
                self.logger.info("Stopping agent...")
                self.running = False
            except Exception as e:
                self.logger.error(f"Agent loop error: {e}")
                time.sleep(30)

def main():
    parser = argparse.ArgumentParser(description='FIM Agent')
    parser.add_argument('--config', default='config/agent_config.yaml', help='Path to config file')
    args = parser.parse_args()

    try:
        agent = FIMAgent(args.config)
        agent.run_daemon()
    except Exception as e:
        logger.error(f"Agent error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()

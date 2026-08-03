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
import fnmatch
import logging
import stat as stat_mod
import platform
import socket
import threading
import subprocess
import re
import difflib
import requests
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

# Extensions worth diffing on change — mirrors
# frontend/src/lib/reportGrouping.ts's DEFAULT_DETAIL_EXTENSIONS. Kept as two
# short, independently-maintained constants rather than a shared-config
# mechanism; update both if this list ever changes.
DETAIL_EXTENSIONS = ('.conf', '.cfg', '.yaml', '.yml', '.ini', '.json')
CONTENT_DIFF_MAX_LINES = 200

# Pause/resume: how often an in-progress scan checkpoints its incremental
# cache (merged, not final) so a paused/interrupted scan can resume without
# re-hashing everything it already did. Whichever threshold hits first.
CHECKPOINT_EVERY_FILES = 200
CHECKPOINT_EVERY_SECONDS = 30

# Content diffing: skip anything above this size entirely -- no shadow
# copy, no diff. A unified diff of a multi-MB file isn't useful for human
# review anyway, and without a cap, this feature's disk footprint is
# unbounded: it scales with however large "config-shaped" (.conf/.yaml/
# .json/etc) files happen to get on a given host, which varies wildly
# (a large JSON/YAML data file under /opt, not just small system configs
# under /etc). Found live: 2GB of shadow copies on one real host.
CONTENT_DIFF_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB

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

# GAP #9: agent_config.yaml's server.api_key may be Fernet-encrypted at rest
# (see scripts/gap9_encrypt_api_keys.sh), stored as "+ENC++<ciphertext>". The
# decryption key lives separately at ENC_KEY_FILE, never alongside the config
# it protects. Decrypt here so the real plaintext key is what actually gets
# sent as X-API-Key — sending the ciphertext as-is (the previous behavior)
# silently defeated the whole point of encrypting it: whoever reads the
# "encrypted" config file could authenticate with that string directly,
# without ever needing the key file.
ENC_PREFIX = "+ENC++"
ENC_KEY_FILE = "/etc/fim/agent-encrypt.key"

def _decrypt_api_key(value: str) -> str:
    if not value or not value.startswith(ENC_PREFIX):
        return value  # plaintext — used as-is (e.g. before gap9 encryption is run)
    from cryptography.fernet import Fernet
    with open(ENC_KEY_FILE, 'rb') as kf:
        cipher = Fernet(kf.read().strip())
    return cipher.decrypt(value[len(ENC_PREFIX):].encode()).decode()

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

    def register_agent(self, hostname: str, ip_address: str, script_hash: Optional[str] = None,
                        current_config: Optional[Dict] = None) -> Optional[str]:
        """Register agent with server"""
        try:
            data = {
                'hostname': hostname,
                'ip_address': ip_address,
                'os_type': platform.system(),
                'os_version': platform.release(),
                'agent_version': '1.0.0'
            }
            if script_hash:
                data['script_hash'] = script_hash
            if current_config:
                data['current_config'] = current_config

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

    def send_heartbeat(self, agent_id: str, hostname: str, script_hash: Optional[str] = None,
                       current_config: Optional[Dict] = None, scan_status: Optional[str] = None,
                       scan_progress: Optional[Dict] = None) -> Dict:
        """
        Send heartbeat to server. Returns a dict always (rather than the
        previous bool/"SCAN_REQUIRED" sentinel mix) since there are several
        independent signals to carry back: scan_required, config_version,
        and scan_pause_requested (the server's desired pause/resume state,
        checked periodically by an in-progress scan — see FIMAgent.run_scan).
        {'ok': bool, 'scan_required': bool, 'config_version': Optional[int],
         'scan_pause_requested': bool}
        """
        try:
            data = {
                'agent_id': agent_id,
                'hostname': hostname,
                'timestamp': datetime.utcnow().isoformat()
            }
            if script_hash:
                data['script_hash'] = script_hash
            if current_config:
                data['current_config'] = current_config
            if scan_status:
                data['scan_status'] = scan_status
            if scan_progress:
                data['scan_progress'] = scan_progress

            response = self.session.post(
                f'{self.server_url}/api/v1/agents/heartbeat',
                json=data,
                timeout=10
            )
            response.raise_for_status()

            scan_required = False
            config_version = None
            scan_pause_requested = False
            try:
                resp_data = response.json()
                if isinstance(resp_data, dict):
                    scan_required = bool(resp_data.get('scan_required'))
                    config_version = resp_data.get('config_version')
                    scan_pause_requested = bool(resp_data.get('scan_pause_requested'))
                    if scan_required:
                        self.logger.info("Received on-demand scan request from server")
            except Exception as json_err:
                self.logger.warning(f"Failed to parse heartbeat response: {json_err}")

            self.logger.debug("Heartbeat sent")
            return {
                'ok': True, 'scan_required': scan_required, 'config_version': config_version,
                'scan_pause_requested': scan_pause_requested,
            }

        except Exception as e:
            self.logger.error(f"Heartbeat failed: {e}")
            return {
                'ok': False, 'scan_required': False, 'config_version': None,
                'scan_pause_requested': False,
            }

    def fetch_agent_config(self, agent_id: str) -> Optional[Dict]:
        """GET the server's desired config for this agent. None on any failure — caller keeps running current config."""
        try:
            response = self.session.get(
                f'{self.server_url}/api/v1/agents/{agent_id}/config', timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"Failed to fetch agent config: {e}")
            return None

    def ack_agent_config(self, agent_id: str, version: int) -> bool:
        """Confirm to the server that a config version was applied."""
        try:
            response = self.session.post(
                f'{self.server_url}/api/v1/agents/{agent_id}/config/ack',
                json={'version': version}, timeout=10
            )
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.error(f"Failed to ack agent config: {e}")
            return False

    def send_scan_results(self, agent_id: str, scan_data: List[Dict], scan_type: str = 'full'):
        """
        Send scan results to server. The server used to "verify" an
        HMAC-SHA256 signature computed from this same request's own
        X-API-Key header — a self-consistency check, not real
        authentication (any caller could invent a key and sign with it).
        Now that the server checks the real, established per-agent key
        (see app/core/agent_auth.py), that signing added complexity with
        no security benefit — X-API-Key is already sent on every request
        via this session's persistent headers (see __init__), so nothing
        else is needed here.
        """
        try:
            data = {
                'agent_id': agent_id,
                'files': scan_data,
                'timestamp': datetime.utcnow().isoformat(),
                'total_files': len(scan_data),
                'scan_type': scan_type
            }
            response = self.session.post(
                f'{self.server_url}/api/v1/scans/submit',
                json=data,
                timeout=30
            )
            response.raise_for_status()
            self.logger.info(f"Scan results sent: {len(scan_data)} files")
            return True

        except Exception as e:
            self.logger.error(f"Failed to send scan results: {e}")
            return False

class FileScanner:
    def __init__(self, paths: List[Union[str, Dict]], hash_algo: str = 'sha256',
                 cache_path: Optional[str] = None,
                 audit_critical_paths: Optional[set] = None,
                 content_shadow_dir: Optional[str] = None):
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

        # Content diffing: local-only shadow copies of config-extension files
        # (DETAIL_EXTENSIONS) so a real unified diff can be computed on the
        # next change — never sent to the server, only the resulting diff
        # text is. Measured ~1MB/122 files across a real deployment's
        # monitored paths (/etc, /var/www, /opt), so scoped broadly (every
        # matching file, not just the auditd critical-path list) is fine.
        self.content_shadow_dir = content_shadow_dir

    def _load_cache(self) -> Dict[str, Dict]:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return {}
        try:
            with open(self.cache_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load scan cache, starting fresh: {e}")
            return {}

    def _save_cache(self, final: bool = True):
        """
        final=True (end of a completed scan): write self._new_cache alone,
        so files that no longer exist drop out of the cache instead of
        lingering forever.

        final=False (mid-scan checkpoint, for pause/resume): merge
        self._prev_cache under self._new_cache instead. self._new_cache only
        holds entries for files reached so far this pass — writing it alone
        would make every not-yet-reached file look uncached on a resume,
        forcing a full re-hash of the entire remaining tree instead of just
        the files that actually still need it.

        Also updates self._prev_cache in memory, unconditionally, even if
        persisting to disk below fails or there's no cache_path at all.
        Without this, _prev_cache was only ever set once, at __init__ (load
        from disk) -- for a long-running agent process doing many scans
        without a restart (the normal, intended mode of operation), every
        scan after the first compared against that same, increasingly
        stale, process-start snapshot instead of what the *previous* scan
        (within this same process) had just learned. Any file not already
        in the cache file at process start got rehashed on literally every
        subsequent scan for the rest of the process's life, never
        "graduating" to the fast unchanged-skip path. Found live: two
        consecutive scans reporting the exact same "22339 hashed" count.
        """
        data = self._new_cache if final else {**self._prev_cache, **self._new_cache}
        self._prev_cache = data
        if not self.cache_path:
            return
        try:
            tmp_path = self.cache_path + '.tmp'
            with open(tmp_path, 'w') as f:
                json.dump(data, f)
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

    @staticmethod
    def _is_agent_internal_path(path: str, content_shadow_dir: Optional[str],
                                 cache_path: Optional[str] = None) -> bool:
        """
        True if `path` is one of the agent's own bookkeeping locations --
        the content-shadow directory (or anything under it), or the
        incremental-scan cache file itself -- neither of which should ever
        be treated as a monitored target or a real-time-watch trigger.
        Checked independently of user-configured exclude_patterns: both
        typically live inside the agent's own config directory, which can
        itself sit under a monitored path (e.g. /opt) without an exclude
        pattern that happens to catch either one.

        Two distinct self-triggering loops came from missing this:
        - Shadow dir: if ever walked, the shadow copies it holds (real
          files matching DETAIL_EXTENSIONS) get treated as new scan
          targets, which get shadow-copied *again* one path segment
          deeper -- forever, until hitting ENAMETOOLONG. Found live: a
          scan's file count exploding from ~86K to 160K+ this way.
        - Cache file: it ends in .json (a DETAIL_EXTENSIONS match) and is
          rewritten via an atomic rename at the end of every scan -- a
          real filesystem event the real-time watcher sees and reacts to,
          triggering another scan, which rewrites the cache again,
          forever. Found live: a scan starting again within seconds of
          the previous one finishing, indefinitely, with nothing external
          actually changing.

        Static (rather than an instance method reading self.* attributes)
        so _RealtimeChangeHandler can reuse the exact same check -- the
        real-time watcher has its own, separate path into the filesystem
        (inotify events, not FileScanner's os.walk) and needs the same
        exclusions just as much.
        """
        target = os.path.abspath(path)
        if content_shadow_dir:
            shadow = os.path.abspath(content_shadow_dir)
            if target == shadow or target.startswith(shadow + os.sep):
                return True
        if cache_path and target == os.path.abspath(cache_path):
            return True
        return False

    def _count_files(self) -> int:
        """
        Cheap pre-pass: count eligible files (respecting exclude_patterns)
        without reading or hashing anything — just the same directory-prune
        walk the real pass does, minus _process_file. Powers an accurate
        progress total instead of a stale guess from the last scan.
        """
        total = 0
        for path_config in self.path_configs:
            path = path_config['path']
            exclude_patterns = path_config['exclude_patterns']
            if not path or not os.path.exists(path):
                continue
            if os.path.isfile(path):
                if not self._is_excluded(path, path, exclude_patterns) and not self._is_agent_internal_path(path, self.content_shadow_dir, self.cache_path):
                    total += 1
            else:
                for root, dirs, files in os.walk(path):
                    if self._is_agent_internal_path(root, self.content_shadow_dir, self.cache_path):
                        dirs[:] = []
                        continue
                    dirs[:] = [
                        d for d in dirs
                        if not self._is_excluded(os.path.join(root, d), path, exclude_patterns)
                        and not self._is_agent_internal_path(os.path.join(root, d), self.content_shadow_dir, self.cache_path)
                    ]
                    total += sum(
                        1 for file in files
                        if not self._is_excluded(os.path.join(root, file), path, exclude_patterns)
                        and not self._is_agent_internal_path(os.path.join(root, file), self.content_shadow_dir, self.cache_path)
                    )
        return total

    def scan(self, progress_fn=None, pause_requested_fn=None,
             accurate_total: bool = True) -> Tuple[List[Dict], bool]:
        """
        Scan all monitored paths, honoring each path's own exclude_patterns.

        progress_fn(processed, total), if given, is called periodically as
        the scan proceeds. pause_requested_fn(), if given, is checked before
        every file — when it returns True, the scan checkpoints immediately
        and stops early instead of continuing, leaving the remaining files
        for the next trigger to pick up (see _save_cache's final=False mode).

        accurate_total controls how the progress total is computed: True
        (typically a scheduled/manual full scan, where accurate progress
        actually matters) does a real _count_files() pre-pass; False
        (typically a realtime-triggered rescan, usually near-instant) uses
        len(self._prev_cache) as a cheap estimate instead of walking the
        whole tree twice for a scan that doesn't need a progress bar anyway.

        Returns (results, paused) — paused is True if pause_requested_fn cut
        the scan short.
        """
        results = []
        self.logger.info(f"Starting scan of {len(self.path_configs)} paths")
        # Rebuilt fresh each cycle (not merged) so files that no longer exist
        # don't linger in the cache forever — final _save_cache() still does
        # this; only the periodic mid-scan checkpoints merge with _prev_cache.
        self._new_cache = {}
        self.hashes_skipped = 0
        self.hashes_computed = 0

        total = 0
        if progress_fn:
            total = self._count_files() if accurate_total else len(self._prev_cache)

        processed = 0
        last_checkpoint_count = 0
        last_checkpoint_time = time.time()
        paused = False

        def _checkpoint(force: bool = False):
            nonlocal last_checkpoint_count, last_checkpoint_time
            if force or (processed - last_checkpoint_count >= CHECKPOINT_EVERY_FILES
                         or time.time() - last_checkpoint_time >= CHECKPOINT_EVERY_SECONDS):
                self._save_cache(final=False)
                last_checkpoint_count = processed
                last_checkpoint_time = time.time()
            if progress_fn:
                progress_fn(processed, total)

        def _process_one(file_path: str):
            nonlocal processed
            file_info = self._process_file(file_path)
            if file_info:
                results.append(file_info)
            processed += 1
            _checkpoint()

        for path_config in self.path_configs:
            if paused:
                break
            path = path_config['path']
            exclude_patterns = path_config['exclude_patterns']

            if not path or not os.path.exists(path):
                self.logger.warning(f"Path not found: {path}")
                continue

            if os.path.isfile(path):
                if pause_requested_fn and pause_requested_fn():
                    paused = True
                    break
                if self._is_excluded(path, path, exclude_patterns) or self._is_agent_internal_path(path, self.content_shadow_dir, self.cache_path):
                    continue
                _process_one(path)
            else:
                for root, dirs, files in os.walk(path):
                    if self._is_agent_internal_path(root, self.content_shadow_dir, self.cache_path):
                        dirs[:] = []
                        continue
                    # Prune excluded directories in place so os.walk never
                    # descends into them at all (not just filters after the
                    # fact) — this is what actually stops /opt/IBM/* from
                    # being scanned, instead of just discarding the results.
                    # Also always prunes the content-shadow dir itself,
                    # independent of exclude_patterns (see _is_agent_internal_path).
                    dirs[:] = [
                        d for d in dirs
                        if not self._is_excluded(os.path.join(root, d), path, exclude_patterns)
                        and not self._is_agent_internal_path(os.path.join(root, d), self.content_shadow_dir, self.cache_path)
                    ]
                    for file in files:
                        if pause_requested_fn and pause_requested_fn():
                            paused = True
                            break
                        file_path = os.path.join(root, file)
                        if self._is_excluded(file_path, path, exclude_patterns):
                            continue
                        if self._is_agent_internal_path(file_path, self.content_shadow_dir, self.cache_path):
                            continue
                        _process_one(file_path)
                    if paused:
                        break

        if paused:
            _checkpoint(force=True)
            self.logger.info(
                f"Scan paused: {processed}/{total or '?'} files processed "
                f"({self.hashes_computed} hashed, {self.hashes_skipped} unchanged/skipped) "
                f"— will resume on next trigger"
            )
        else:
            self._save_cache(final=True)
            if progress_fn:
                progress_fn(processed, total)
            self.logger.info(
                f"Scan complete: {len(results)} files scanned "
                f"({self.hashes_computed} hashed, {self.hashes_skipped} unchanged/skipped)"
            )
        return results, paused

    def _process_file(self, file_path: str) -> Optional[Dict]:
        try:
            stat = os.stat(file_path)

            # Refuse to hash anything but a regular file. A character
            # device (e.g. something under a monitored tree that resolves
            # to /dev/urandom or similar) never reaches EOF, so
            # calculate_hash's read loop would spin forever -- hashing 100%
            # CPU, never returning, permanently blocking every future scan
            # (trigger_scan treats a still-alive scan thread as "already
            # running"). FIFOs/sockets have similar failure modes. Found
            # live: a scan wedged for over a day hashing exactly this.
            if not stat_mod.S_ISREG(stat.st_mode):
                self.logger.warning(f"Skipping non-regular file (device/FIFO/socket): {file_path}")
                return None

            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).isoformat()

            cached = self._prev_cache.get(file_path)
            audit_info = None
            content_diff = None
            if cached and cached.get('mtime') == mtime and cached.get('size') == size:
                file_hash = cached['hash']
                self.hashes_skipped += 1
                # Still establish/refresh the shadow copy for a matching file
                # even though nothing changed — otherwise the shadow only
                # ever gets written lazily on a file's first observed change,
                # meaning that very first edit after deployment always comes
                # back diff-less (nothing to diff against yet) and only the
                # second edit onward produces a real diff.
                if file_path.endswith(DETAIL_EXTENSIONS) and size <= CONTENT_DIFF_MAX_FILE_SIZE:
                    self._diff_content(file_path, changed_since_last_seen=False)
            else:
                file_hash = self.calculate_hash(file_path)
                self.hashes_computed += 1
                changed_since_last_seen = bool(cached and cached.get('hash') != file_hash)
                # Only correlate for a real, locally-detected content change
                # on a critical path — not the first time we've ever seen
                # this file (no local baseline to compare against yet).
                if file_path in self.audit_critical_paths and changed_since_last_seen:
                    audit_info = self._correlate_auditd(file_path)
                if file_path.endswith(DETAIL_EXTENSIONS) and size <= CONTENT_DIFF_MAX_FILE_SIZE:
                    content_diff = self._diff_content(file_path, changed_since_last_seen)

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
            if content_diff:
                result['content_diff'] = content_diff
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

    def _shadow_path(self, file_path: str) -> Optional[str]:
        """Where this file's local content shadow copy lives, mirroring its real path."""
        if not self.content_shadow_dir:
            return None
        rel = file_path.lstrip(os.sep)
        if os.altsep:
            rel = rel.lstrip(os.altsep)
        return os.path.join(self.content_shadow_dir, rel)

    def _diff_content(self, file_path: str, changed_since_last_seen: bool) -> Optional[str]:
        """
        Best-effort unified diff against a local shadow copy of this file's
        previous content (never sent anywhere — only the diff text is).
        Always refreshes the shadow copy so the next change has something
        to diff against; only returns a diff when there's a previous copy
        AND this is a real, locally-detected change, not the first time
        we've ever seen the file. Never raises — a diff failure (binary
        content, permission issue, whatever) must never break the scan;
        the file is still hashed and reported normally either way.
        """
        shadow_path = self._shadow_path(file_path)
        if not shadow_path:
            return None

        try:
            with open(file_path, 'r', encoding='utf-8', errors='strict') as f:
                new_content = f.read()
        except Exception:
            return None  # binary/non-utf8/unreadable — skip diffing, hash-only is fine

        diff_text = None
        if changed_since_last_seen and os.path.exists(shadow_path):
            try:
                with open(shadow_path, 'r', encoding='utf-8', errors='strict') as f:
                    old_content = f.read()
                diff_lines = list(difflib.unified_diff(
                    old_content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile='baseline', tofile='current',
                ))
                if diff_lines:
                    if len(diff_lines) > CONTENT_DIFF_MAX_LINES:
                        truncated = len(diff_lines) - CONTENT_DIFF_MAX_LINES
                        diff_lines = diff_lines[:CONTENT_DIFF_MAX_LINES]
                        diff_lines.append(f"... {truncated} more lines truncated ...\n")
                    diff_text = ''.join(diff_lines)
            except Exception as e:
                self.logger.warning(f"Content diff failed for {file_path}: {e}")

        try:
            os.makedirs(os.path.dirname(shadow_path), exist_ok=True)
            with open(shadow_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        except Exception as e:
            self.logger.warning(f"Failed to update content shadow copy for {file_path}: {e}")

        return diff_text

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
    def __init__(self, base_path: str, exclude_patterns: List[str], mark_dirty,
                 content_shadow_dir: Optional[str] = None, cache_path: Optional[str] = None):
        self.base_path = base_path
        self.exclude_patterns = exclude_patterns
        self.mark_dirty = mark_dirty
        self.content_shadow_dir = content_shadow_dir
        self.cache_path = cache_path

    def _handle(self, event):
        if event.is_directory:
            return
        if FileScanner._is_excluded(event.src_path, self.base_path, self.exclude_patterns):
            return
        # Without this, the agent's own bookkeeping writes -- shadow-copy
        # refreshes every scan (see FileScanner._diff_content), and the
        # incremental-scan cache file's atomic rename at the end of every
        # scan (see FileScanner._save_cache) -- look like real file changes
        # to this watcher, which marks itself dirty and triggers another
        # scan within seconds, which does the same writes again, forever --
        # a scan starting again moments after the last one finished,
        # indefinitely, with nothing external actually changing.
        # FileScanner's own directory walk already excludes both; the
        # real-time watcher has a separate path into the filesystem
        # (inotify events) and needs the same exclusions.
        if FileScanner._is_agent_internal_path(event.src_path, self.content_shadow_dir, self.cache_path):
            return
        self.mark_dirty()

    # Only these four correspond to an actual content/inventory change.
    # watchdog's inotify backend also emits FileOpenedEvent/FileClosedEvent
    # for every read of a watched file (including our own scanner hashing
    # files, or unrelated processes just opening e.g. /etc/hosts every few
    # seconds) — reacting to those via on_any_event kept resetting the
    # debounce timer from background noise, so the "quiet period" needed to
    # actually trigger a rescan never arrived.
    def on_created(self, event):
        self._handle(event)

    def on_modified(self, event):
        self._handle(event)

    def on_deleted(self, event):
        self._handle(event)

    def on_moved(self, event):
        self._handle(event)


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
            _decrypt_api_key(self.config['server']['api_key'])
        )
        
        cache_path = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), '.scan_cache.json'
        )
        content_shadow_dir = os.path.join(
            os.path.dirname(os.path.abspath(config_file)), '.content_shadow'
        )
        try:
            os.makedirs(content_shadow_dir, mode=0o700, exist_ok=True)
        except Exception as e:
            self.logger.warning(f"Could not create content shadow dir, content diffing disabled: {e}")
            content_shadow_dir = None
        self.scanner = FileScanner(
            self.monitored_paths,
            self.config['monitoring'].get('hash_algorithm', 'sha256'),
            cache_path=cache_path,
            audit_critical_paths=self.config['monitoring'].get('audit_critical_paths'),
            content_shadow_dir=content_shadow_dir,
        )

        self.hostname = socket.gethostname()
        self.ip_address = socket.gethostbyname(self.hostname)
        self.agent_id = self.config['agent'].get('id')
        self.running = True

        # Self-integrity: hash our own running script once at startup and
        # report it on every register/heartbeat. Server remembers the first
        # hash it sees as "known good" and alerts on a later mismatch — this
        # catches an accidentally-reverted or tampered script, not a
        # sophisticated attacker who also patches this reporting code.
        # Best-effort: a read failure here must never stop the agent.
        self.script_hash = None
        try:
            with open(os.path.abspath(__file__), 'rb') as f:
                self.script_hash = hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            self.logger.warning(f"Could not hash own script for self-integrity check: {e}")

        # Item 11: fleet config push. Persisted in agent_config.yaml itself
        # (same file save_agent_id already reads/writes) rather than a new
        # state file — 0 if never set, meaning "always fetch on first
        # heartbeat that reports a config_version > 0".
        self.applied_config_version = self.config['agent'].get('config_version', 0)

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

        # Scan pause/resume + progress reporting. Decoupled from the
        # heartbeat loop (see trigger_scan/run_daemon) so a long scan no
        # longer blocks heartbeats for its entire duration. _scan_state is
        # reported every heartbeat; _pause_requested is the server's
        # last-known desired state, read back from each heartbeat response
        # and checked periodically by an in-progress scan.
        self._scan_thread = None
        self._scan_state_lock = threading.Lock()
        self._scan_state = {"status": "idle", "processed": 0, "total": 0}
        self._pause_lock = threading.Lock()
        self._pause_requested = False

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
                    path, path_config['exclude_patterns'], self._mark_realtime_dirty,
                    content_shadow_dir=self.scanner.content_shadow_dir,
                    cache_path=self.scanner.cache_path,
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
        self.trigger_scan(scan_type='realtime')
        return True

    def _current_config_payload(self) -> Dict:
        """
        What we're actually monitoring right now, in the same {path,
        exclude_patterns} shape the config-push feature uses — reported so
        the admin config editor can pre-fill with reality instead of a
        blank form on agents nothing's ever been pushed to. Purely for
        display; doesn't participate in the push/apply/ack protocol.
        """
        return {"paths": self.scanner.path_configs}

    def register(self):
        """Register agent with server"""
        self.logger.info("Registering agent...")
        self.agent_id = self.client.register_agent(
            self.hostname, self.ip_address, self.script_hash, self._current_config_payload()
        )
        
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

    def _apply_agent_config(self, config_version: int):
        """
        Fetch and apply a newer config version pushed from the server (see
        app/api/agents.py's PUT .../config). Writes only monitoring.paths
        into agent_config.yaml — leaves server url/api_key/everything else
        untouched — then hot-reloads self.scanner and the real-time watcher
        in place, no process restart. Any failure here (malformed config,
        unreachable server) must leave the agent running on its current
        config, never crash it.
        """
        try:
            remote = self.client.fetch_agent_config(self.agent_id)
            if not remote or not remote.get('desired_config'):
                return
            paths = remote['desired_config'].get('paths')
            if not isinstance(paths, list) or not paths:
                self.logger.warning("Received empty/invalid config push — ignoring")
                return

            with open(self.config_path, 'r') as f:
                yaml_config = yaml.safe_load(f)
            yaml_config.setdefault('monitoring', {})['paths'] = paths
            yaml_config.setdefault('agent', {})['config_version'] = config_version
            with open(self.config_path, 'w') as f:
                yaml.dump(yaml_config, f, default_flow_style=False)

            # Hot-reload: FileScanner is cheap to reconstruct, no restart needed.
            self.config = AgentConfig(self.config_path)
            self.monitored_paths = paths
            cache_path = os.path.join(
                os.path.dirname(os.path.abspath(self.config_path)), '.scan_cache.json'
            )
            self.scanner = FileScanner(
                self.monitored_paths,
                self.config['monitoring'].get('hash_algorithm', 'sha256'),
                cache_path=cache_path,
                audit_critical_paths=self.config['monitoring'].get('audit_critical_paths'),
                content_shadow_dir=self.scanner.content_shadow_dir,
            )

            # Real-time watcher was watching the OLD paths — restart it.
            if self._observer:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=5)
                except Exception:
                    pass
                self._observer = None
            self.start_realtime_watch()

            self.applied_config_version = config_version
            self.logger.info(
                f"Applied pushed config (version {config_version}), "
                f"{len(paths)} monitored path(s)"
            )
            self.client.ack_agent_config(self.agent_id, config_version)
        except Exception as e:
            self.logger.error(f"Failed to apply pushed config: {e}")

    def _set_scan_state(self, status: str, processed: int, total: int):
        with self._scan_state_lock:
            self._scan_state = {"status": status, "processed": processed, "total": total}

    def trigger_scan(self, scan_type: str = 'full'):
        """
        Non-blocking: spawns the scan on its own thread instead of blocking
        the caller — the heartbeat loop calls this instead of run_scan()
        directly so a long scan can never delay a heartbeat.
        """
        with self._pause_lock:
            if self._pause_requested:
                self.logger.debug(f"Scan trigger ({scan_type}) ignored — paused")
                return
        if self._scan_thread and self._scan_thread.is_alive():
            self.logger.debug(f"Scan trigger ({scan_type}) ignored — a scan is already running")
            return
        self._scan_thread = threading.Thread(target=self.run_scan, args=(scan_type,), daemon=True)
        self._scan_thread.start()

    def run_scan(self, scan_type: str = 'full'):
        """
        Execute file integrity scan. Expected to run on its own thread (see
        trigger_scan) — everything here can safely take a long time without
        affecting heartbeats.
        """
        with self._scan_lock:
            with self._pause_lock:
                if self._pause_requested:
                    self.logger.info(f"Scan ({scan_type}) not started — pause requested")
                    return

            self.logger.info(f"Starting file integrity scan (scan_type={scan_type})")
            self._set_scan_state("running", 0, 0)

            def _progress(processed, total):
                self._set_scan_state("running", processed, total)

            def _pause_requested_fn():
                with self._pause_lock:
                    return self._pause_requested

            scan_results, paused = self.scanner.scan(
                progress_fn=_progress,
                pause_requested_fn=_pause_requested_fn,
                accurate_total=(scan_type == 'full'),
            )

            with self._scan_state_lock:
                processed, total = self._scan_state["processed"], self._scan_state["total"]
            self._set_scan_state("paused" if paused else "idle", processed, total)

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

        # Initial scan — non-blocking, so start_realtime_watch() and the
        # heartbeat loop below both start immediately rather than waiting
        # for a potentially long first scan to finish.
        self.trigger_scan('full')
        self.start_realtime_watch()

        last_scan = time.time()
        scan_interval = self.config['monitoring'].get('scan_interval', 3600)
        heartbeat_interval = self.config['monitoring'].get('heartbeat_interval', 60)

        while self.running:
            try:
                with self._scan_state_lock:
                    scan_status = self._scan_state["status"]
                    scan_progress = {
                        "processed": self._scan_state["processed"],
                        "total": self._scan_state["total"],
                    }

                # Heartbeat — always sent on schedule regardless of whether
                # a scan is currently running (see trigger_scan/run_scan).
                result = self.client.send_heartbeat(
                    self.agent_id, self.hostname, self.script_hash, self._current_config_payload(),
                    scan_status=scan_status, scan_progress=scan_progress,
                )

                with self._pause_lock:
                    self._pause_requested = bool(result.get('scan_pause_requested'))

                # Check if scan requested
                if result.get('scan_required'):
                    self.trigger_scan('full')
                    last_scan = time.time()  # Reset scheduled scan timer

                # Check if a newer config was pushed
                config_version = result.get('config_version')
                if config_version is not None and config_version > self.applied_config_version:
                    self._apply_agent_config(config_version)

                # Scheduled scan
                if time.time() - last_scan > scan_interval:
                    self.trigger_scan('full')
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

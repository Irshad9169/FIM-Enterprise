"""
Report grouping/categorization -- Python port of
frontend/src/lib/reportGrouping.ts, so the RT-published report (built here,
server-side) shows the same category buckets / host-clubbing / directory
rollups the on-screen report UI does, instead of a flat per-file listing.

Keep this in sync with reportGrouping.ts by hand -- there's no shared
source of truth between the two runtimes. Constants and algorithms below
are intentionally identical to that file; see its own comments for the
full design rationale (project memory "report-grouping-design-pending").

Each `changes` list here is a list of dicts shaped like the per-change
dicts app/api/reports.py's _build_publish_agents_data builds: file_path,
change_type, severity, baseline_hash, current_hash, baseline_size,
current_size, analyst_notes, is_known_change, requires_investigation,
baseline_mtime, current_mtime, audit_uid, audit_process, audit_command
(mtimes as ISO strings or None).
"""
from typing import Dict, List, Optional, Tuple

# ── Category keywords ────────────────────────────────────────────────────
DEFAULT_CATEGORY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("kernel", ["kernel", "/modules/", ".build-id", "vmlinuz", "initramfs"]),
    ("grub", ["grub", "/boot/"]),
    ("httpd", ["httpd"]),
    ("apache", ["apachectl", "apache2"]),
    ("conf", [".conf"]),
]

DEFAULT_DETAIL_EXTENSIONS = [".conf", ".cfg", ".yaml", ".yml", ".ini", ".json"]

DEFAULT_CLUB_THRESHOLD = 0.9

MAX_SAMPLES_PER_BUCKET = 4
ROLLUP_MIN_COUNT = 20
MAX_GROUP_HOSTS_SHOWN = 50
MIN_ROLLUP_DEPTH = 2


def _normalized_type(c: Dict) -> str:
    return (c.get("change_type") or "").lower()


def dedupe_by_latest_mtime(changes: List[Dict]) -> List[Dict]:
    """Collapse repeated (change_type, file_path) entries down to the most
    recent by current_mtime -- same file can legitimately show up more than
    once in a day (e.g. two separate password resets touching /etc/shadow)."""
    latest: Dict[str, Dict] = {}
    for c in changes:
        key = f"{_normalized_type(c)}:{c.get('file_path')}"
        existing = latest.get(key)
        if existing is None:
            latest[key] = c
            continue
        # ISO 8601 strings sort lexicographically the same as chronologically.
        if (c.get("current_mtime") or "") >= (existing.get("current_mtime") or ""):
            latest[key] = c
    return list(latest.values())


def categorize_file(path: str, keywords: List[Tuple[str, List[str]]] = DEFAULT_CATEGORY_KEYWORDS) -> str:
    lower = path.lower()
    for label, kws in keywords:
        if any(kw in lower for kw in kws):
            return label
    return "other"


def is_detail_worthy(path: str, extensions: List[str] = DEFAULT_DETAIL_EXTENSIONS) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in extensions)


def build_buckets(
    changes: List[Dict], change_type: str,
    keywords: List[Tuple[str, List[str]]] = DEFAULT_CATEGORY_KEYWORDS,
) -> List[Dict]:
    """Group one change_type's changes into category buckets."""
    relevant = [c for c in changes if _normalized_type(c) == change_type]
    by_category: Dict[str, List[Dict]] = {}
    for c in relevant:
        cat = categorize_file(c.get("file_path") or "", keywords)
        by_category.setdefault(cat, []).append(c)

    buckets = []
    for category, items in by_category.items():
        samples = [c.get("file_path") for c in items[:MAX_SAMPLES_PER_BUCKET]]
        buckets.append({
            "category": category,
            "count": len(items),
            "samples": samples,
            "more_count": max(0, len(items) - len(samples)),
        })

    # Largest first; "other" always last regardless of size.
    buckets.sort(key=lambda b: (b["category"] == "other", -b["count"]))
    return buckets


def _parent_of(directory: str) -> Optional[str]:
    """One level up from `directory` (which always ends in '/'), or None if
    that would go above MIN_ROLLUP_DEPTH."""
    trimmed = directory[:-1] if directory.endswith("/") else directory
    idx = trimmed.rfind("/")
    if idx <= 0:
        return None
    parent = trimmed[: idx + 1]
    depth = len([seg for seg in parent.split("/") if seg])
    return parent if depth >= MIN_ROLLUP_DEPTH else None


def _merge_sibling_rollups(entries: Dict[str, int]) -> Dict[str, int]:
    """Merge 2+ sibling directory rollups sharing a parent into one combined
    line at that parent, repeating until a pass produces no further merges.
    Always terminates -- _parent_of is bounded by MIN_ROLLUP_DEPTH."""
    current = dict(entries)
    while True:
        by_parent: Dict[str, List[str]] = {}
        for directory in current:
            parent = _parent_of(directory)
            if parent is None:
                continue
            by_parent.setdefault(parent, []).append(directory)

        next_entries = dict(current)
        merged_any = False
        for parent, dirs in by_parent.items():
            if len(dirs) < 2:
                continue
            total = sum(current.get(d, 0) for d in dirs)
            for d in dirs:
                next_entries.pop(d, None)
            next_entries[parent] = next_entries.get(parent, 0) + total
            merged_any = True

        current = next_entries
        if not merged_any:
            return current


def build_directory_rollups(changes: List[Dict], change_type: str) -> List[Dict]:
    """Roll up large added/removed subtrees into one line instead of listing
    every file, merging sibling subdirectories under a shared parent."""
    relevant = [c for c in changes if _normalized_type(c) == change_type]
    by_dir: Dict[str, int] = {}
    for c in relevant:
        path = c.get("file_path") or ""
        idx = path.rfind("/")
        directory = path[: idx + 1] if idx > 0 else "/"
        by_dir[directory] = by_dir.get(directory, 0) + 1

    # Only already-qualifying directories are merge candidates -- don't sum
    # small unrelated subdirectories together just because their total
    # happens to cross the threshold.
    qualifying = {d: n for d, n in by_dir.items() if n >= ROLLUP_MIN_COUNT}
    merged = _merge_sibling_rollups(qualifying)

    return sorted(
        ({"directory": d, "count": n} for d, n in merged.items()),
        key=lambda r: -r["count"],
    )


def build_detail_entries(
    changes: List[Dict], extensions: List[str] = DEFAULT_DETAIL_EXTENSIONS,
) -> List[Dict]:
    """Changed files worth showing individually: matches a detail-worthy
    extension, or carries auditd attribution regardless of extension
    (critical-path files like /etc/passwd have no matching extension but
    attribution is exactly the kind of detail this section exists for)."""
    return [
        c for c in changes
        if _normalized_type(c) == "changed"
        and (
            is_detail_worthy(c.get("file_path") or "", extensions)
            or bool(c.get("audit_uid") or c.get("audit_process") or c.get("audit_command"))
        )
        and (c.get("baseline_mtime") or c.get("current_mtime"))
    ]


# ── Host clubbing ─────────────────────────────────────────────────────────

def _change_fingerprint(c: Dict) -> str:
    """Path + change type only -- hash deliberately excluded (see
    reportGrouping.ts's changeFingerprint for the full reasoning: analysts
    club by "did the same file change," not byte-identical content)."""
    return f"{_normalized_type(c)}:{c.get('file_path')}"


def compute_similarity(a: List[Dict], b: List[Dict]) -> float:
    """Jaccard similarity between two hosts' change sets, by fingerprint."""
    if not a and not b:
        return 1.0
    set_a = {_change_fingerprint(c) for c in a}
    set_b = {_change_fingerprint(c) for c in b}
    intersection = len(set_a & set_b)
    union = len(set_a) + len(set_b) - intersection
    return 1.0 if union == 0 else intersection / union


def club_hosts(hosts: List[Dict], threshold: float = DEFAULT_CLUB_THRESHOLD) -> Dict[str, List[Dict]]:
    """
    Greedy single-pass clustering, matching reportGrouping.ts's clubHosts:
    each unclubbed host becomes a seed, and any remaining host similar
    enough to *that seed* (not the growing merged set) joins its group.
    `hosts`: [{"hostname": str, "changes": [...]}, ...].
    Returns {"groups": [{"hostnames": [...], "changes": [...]}], "solos": [{"hostname":..., "changes":...}]}.
    """
    remaining = [
        {"hostname": h["hostname"], "changes": dedupe_by_latest_mtime(h["changes"])}
        for h in hosts
    ]
    groups: List[Dict] = []
    solos: List[Dict] = []

    while remaining:
        seed = remaining.pop(0)
        members = [seed]

        i = len(remaining) - 1
        while i >= 0:
            candidate = remaining[i]
            if compute_similarity(seed["changes"], candidate["changes"]) >= threshold:
                members.append(candidate)
                remaining.pop(i)
            i -= 1

        if len(members) >= 2:
            seen = set()
            merged: List[Dict] = []
            for m in members:
                for c in m["changes"]:
                    key = _change_fingerprint(c)
                    if key not in seen:
                        seen.add(key)
                        merged.append(c)
            groups.append({"hostnames": [m["hostname"] for m in members], "changes": merged})
        else:
            solos.append(seed)

    return {"groups": groups, "solos": solos}

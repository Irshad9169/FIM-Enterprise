"""
Unit tests for app/services/report_grouping.py -- the Python port of
frontend/src/lib/reportGrouping.ts, used by ticket_linker.py's
_build_publish_content so the RT-published report shows the same
category-bucket / host-clubbing / directory-rollup grouping the report UI
does, instead of a flat per-file listing.
"""
from app.services import report_grouping as rg


def _c(path, ctype="added", **kw):
    d = {
        "file_path": path, "change_type": ctype, "severity": "medium",
        "baseline_hash": None, "current_hash": "x", "baseline_size": None,
        "current_size": 1, "analyst_notes": None, "is_known_change": False,
        "requires_investigation": False, "baseline_mtime": None,
        "current_mtime": None, "audit_uid": None, "audit_process": None,
        "audit_command": None,
    }
    d.update(kw)
    return d


# ── categorize_file / is_detail_worthy ──────────────────────────────────────

def test_categorize_file_matches_keyword():
    assert rg.categorize_file("/usr/lib/modules/5.4.0/foo.ko") == "kernel"
    assert rg.categorize_file("/etc/sysctl.conf") == "conf"
    assert rg.categorize_file("/some/random/path") == "other"


def test_categorize_file_first_matching_keyword_wins():
    # Contains both "httpd" (checked earlier) and ".conf" (checked later)
    # in DEFAULT_CATEGORY_KEYWORDS -- httpd must win.
    assert rg.categorize_file("/etc/httpd/conf/httpd.conf") == "httpd"


def test_is_detail_worthy_checks_extension():
    assert rg.is_detail_worthy("/etc/foo.conf") is True
    assert rg.is_detail_worthy("/etc/foo.ko") is False


# ── build_buckets ────────────────────────────────────────────────────────────

def test_build_buckets_groups_by_category_with_sample_cap():
    changes = [_c(f"/usr/lib/modules/5.4.0/mod{i}.ko") for i in range(10)]
    buckets = rg.build_buckets(changes, "added")
    assert len(buckets) == 1
    b = buckets[0]
    assert b["category"] == "kernel"
    assert b["count"] == 10
    assert len(b["samples"]) == rg.MAX_SAMPLES_PER_BUCKET
    assert b["more_count"] == 10 - rg.MAX_SAMPLES_PER_BUCKET


def test_build_buckets_other_sorts_last_regardless_of_size():
    changes = (
        [_c(f"/random/file{i}.bin") for i in range(50)]  # "other", huge
        + [_c("/etc/sysctl.conf")]                        # "conf", tiny
    )
    buckets = rg.build_buckets(changes, "added")
    assert buckets[-1]["category"] == "other"
    assert buckets[0]["category"] == "conf"


def test_build_buckets_ignores_other_change_types():
    changes = [_c("/etc/foo.conf", ctype="removed")]
    assert rg.build_buckets(changes, "added") == []


# ── build_directory_rollups ──────────────────────────────────────────────────

def test_directory_rollups_merge_qualifying_siblings():
    changes = (
        [_c(f"/usr/lib/modules/5.4.0/kernel/net/mod{i}.ko") for i in range(25)]
        + [_c(f"/usr/lib/modules/5.4.0/kernel/drivers/mod{i}.ko") for i in range(22)]
    )
    rollups = rg.build_directory_rollups(changes, "added")
    assert rollups == [{"directory": "/usr/lib/modules/5.4.0/kernel/", "count": 47}]


def test_directory_rollups_lone_qualifying_dir_does_not_merge_upward():
    changes = [_c(f"/usr/lib/modules/5.4.0/kernel/net/mod{i}.ko") for i in range(25)]
    rollups = rg.build_directory_rollups(changes, "added")
    assert rollups == [{"directory": "/usr/lib/modules/5.4.0/kernel/net/", "count": 25}]


def test_directory_rollups_unrelated_trees_stay_separate():
    changes = (
        [_c(f"/usr/local/foo/file{i}.txt") for i in range(25)]
        + [_c(f"/var/log/bar/file{i}.txt") for i in range(25)]
    )
    rollups = rg.build_directory_rollups(changes, "added")
    dirs = {r["directory"] for r in rollups}
    assert dirs == {"/usr/local/foo/", "/var/log/bar/"}


def test_directory_rollups_below_min_count_produces_nothing():
    changes = [_c(f"/usr/lib/modules/file{i}.ko") for i in range(5)]
    assert rg.build_directory_rollups(changes, "added") == []


# ── build_detail_entries ─────────────────────────────────────────────────────

def test_detail_entries_includes_matching_extension():
    changes = [_c("/etc/httpd/conf/httpd.conf", ctype="changed", current_mtime="2026-09-17T00:00:00")]
    assert len(rg.build_detail_entries(changes)) == 1


def test_detail_entries_includes_audit_attribution_regardless_of_extension():
    changes = [_c(
        "/etc/passwd", ctype="changed", current_mtime="2026-09-17T00:00:00",
        audit_uid="0", audit_process="/usr/sbin/useradd",
    )]
    assert len(rg.build_detail_entries(changes)) == 1


def test_detail_entries_excludes_plain_binary_change():
    changes = [_c("/usr/bin/foo", ctype="changed", current_mtime="2026-09-17T00:00:00")]
    assert rg.build_detail_entries(changes) == []


# ── dedupe_by_latest_mtime ───────────────────────────────────────────────────

def test_dedupe_keeps_latest_mtime_for_same_file():
    changes = [
        _c("/etc/shadow", ctype="changed", current_mtime="2026-09-17T09:00:00"),
        _c("/etc/shadow", ctype="changed", current_mtime="2026-09-17T15:00:00"),
    ]
    result = rg.dedupe_by_latest_mtime(changes)
    assert len(result) == 1
    assert result[0]["current_mtime"] == "2026-09-17T15:00:00"


# ── club_hosts ───────────────────────────────────────────────────────────────

def test_club_hosts_groups_identical_change_sets():
    changes = [_c(f"/usr/lib/modules/mod{i}.ko") for i in range(5)]
    hosts = [
        {"hostname": "bsa01", "changes": changes},
        {"hostname": "bsa02", "changes": changes},
        {"hostname": "web01", "changes": [_c("/etc/httpd.conf")]},
    ]
    result = rg.club_hosts(hosts)
    assert len(result["groups"]) == 1
    assert set(result["groups"][0]["hostnames"]) == {"bsa01", "bsa02"}
    assert [s["hostname"] for s in result["solos"]] == ["web01"]


def test_club_hosts_below_threshold_stays_solo():
    hosts = [
        {"hostname": "a", "changes": [_c("/x1"), _c("/x2")]},
        {"hostname": "b", "changes": [_c("/y1"), _c("/y2")]},
    ]
    result = rg.club_hosts(hosts)
    assert result["groups"] == []
    assert len(result["solos"]) == 2


def test_compute_similarity_identical_and_disjoint():
    a = [_c("/x1"), _c("/x2")]
    assert rg.compute_similarity(a, a) == 1.0
    assert rg.compute_similarity(a, [_c("/y1")]) == 0.0

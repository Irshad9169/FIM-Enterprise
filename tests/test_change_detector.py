"""
Unit tests for app/services/change_detector.py — the core FIM diffing and
baseline-integrity logic. These are the functions that decide what counts
as a security-relevant change, so regressions here are the highest-impact
kind this project can ship.

Baseline/WhitelistRule stand-ins use plain SimpleNamespace objects rather
than real SQLAlchemy models — ChangeDetector only reads attributes off
them, so a stub with the right attributes is equivalent for these tests,
with no database involved.
"""
from types import SimpleNamespace

import pytest

from app.services.change_detector import ChangeDetector


def make_baseline(checksum=None, baseline_data=None, id="baseline-1", agent_id="agent-1"):
    return SimpleNamespace(id=id, agent_id=agent_id, checksum=checksum, baseline_data=baseline_data)


def make_rule(rule_type, match_value, id="rule-1"):
    return SimpleNamespace(id=id, rule_type=rule_type, match_value=match_value)


# ── compute_baseline_checksum ─────────────────────────────────────────────

def test_checksum_is_deterministic_regardless_of_key_order():
    data_a = {"files": [{"path": "/etc/passwd", "hash": "abc"}], "count": 1}
    data_b = {"count": 1, "files": [{"path": "/etc/passwd", "hash": "abc"}]}
    assert ChangeDetector.compute_baseline_checksum(data_a) == \
        ChangeDetector.compute_baseline_checksum(data_b)


def test_checksum_changes_when_data_changes():
    data_a = {"files": [{"path": "/etc/passwd", "hash": "abc"}]}
    data_b = {"files": [{"path": "/etc/passwd", "hash": "different"}]}
    assert ChangeDetector.compute_baseline_checksum(data_a) != \
        ChangeDetector.compute_baseline_checksum(data_b)


# ── verify_baseline_integrity ─────────────────────────────────────────────

def test_integrity_passes_for_legacy_baseline_with_no_checksum():
    baseline = make_baseline(checksum=None, baseline_data={"files": []})
    assert ChangeDetector.verify_baseline_integrity(baseline) is True


def test_integrity_passes_when_checksum_matches_data():
    data = {"files": [{"path": "/etc/passwd", "hash": "abc"}]}
    checksum = ChangeDetector.compute_baseline_checksum(data)
    baseline = make_baseline(checksum=checksum, baseline_data=data)
    assert ChangeDetector.verify_baseline_integrity(baseline) is True


def test_integrity_fails_when_checksum_does_not_match_data():
    data = {"files": [{"path": "/etc/passwd", "hash": "abc"}]}
    baseline = make_baseline(checksum="0" * 64, baseline_data=data)
    assert ChangeDetector.verify_baseline_integrity(baseline) is False


def test_integrity_fails_when_checksum_present_but_data_missing():
    baseline = make_baseline(checksum="0" * 64, baseline_data=None)
    assert ChangeDetector.verify_baseline_integrity(baseline) is False


def test_integrity_detects_tampering_after_data_mutation():
    data = {"files": [{"path": "/etc/passwd", "hash": "abc"}]}
    checksum = ChangeDetector.compute_baseline_checksum(data)
    baseline = make_baseline(checksum=checksum, baseline_data=data)
    assert ChangeDetector.verify_baseline_integrity(baseline) is True

    # Simulate a compromised DB row: data mutated, checksum left stale
    baseline.baseline_data["files"][0]["hash"] = "tampered"
    assert ChangeDetector.verify_baseline_integrity(baseline) is False


# ── _severity_for_new_file ────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/etc/passwd", "/etc/shadow", "/bin/bash", "/sbin/init",
    "/usr/bin/sudo", "/usr/sbin/sshd",
])
def test_new_file_in_sensitive_dir_is_high_severity(path):
    assert ChangeDetector._severity_for_new_file(path) == "high"


@pytest.mark.parametrize("path", [
    "/home/user/file.txt", "/var/log/app.log", "/opt/app/config.yaml",
])
def test_new_file_outside_sensitive_dir_is_medium_severity(path):
    assert ChangeDetector._severity_for_new_file(path) == "medium"


# ── _file_changed ──────────────────────────────────────────────────────────

BASE_FILE = {"path": "/etc/passwd", "hash": "abc", "permissions": "644", "owner": "root", "group": "root", "size": 100}


def test_file_changed_false_for_identical_files():
    assert ChangeDetector._file_changed(BASE_FILE, dict(BASE_FILE)) is False


@pytest.mark.parametrize("field,new_value", [
    ("hash", "different"),
    ("permissions", "777"),
    ("owner", "attacker"),
    ("group", "attacker"),
    ("size", 999),
])
def test_file_changed_true_when_field_differs(field, new_value):
    modified = dict(BASE_FILE)
    modified[field] = new_value
    assert ChangeDetector._file_changed(BASE_FILE, modified) is True


# ── _get_change_details ───────────────────────────────────────────────────

def test_change_details_only_includes_changed_fields():
    modified = dict(BASE_FILE)
    modified["hash"] = "newhash"
    details = ChangeDetector._get_change_details(BASE_FILE, modified)
    assert details == {"hash": {"old": "abc", "new": "newhash"}}


def test_change_details_includes_all_differing_fields():
    modified = dict(BASE_FILE)
    modified["hash"] = "newhash"
    modified["owner"] = "attacker"
    details = ChangeDetector._get_change_details(BASE_FILE, modified)
    assert set(details.keys()) == {"hash", "owner"}


# ── _compare_files ─────────────────────────────────────────────────────────

def test_compare_files_detects_created_file():
    changes = ChangeDetector._compare_files(baseline_files=[], scan_files=[dict(BASE_FILE)])
    assert len(changes) == 1
    assert changes[0]["type"] == "created"
    assert changes[0]["path"] == "/etc/passwd"
    assert changes[0]["severity"] == "high"  # /etc path


def test_compare_files_detects_deleted_file():
    changes = ChangeDetector._compare_files(baseline_files=[dict(BASE_FILE)], scan_files=[])
    assert len(changes) == 1
    assert changes[0]["type"] == "deleted"
    assert changes[0]["severity"] == "high"


def test_compare_files_detects_modified_file():
    modified = dict(BASE_FILE)
    modified["hash"] = "newhash"
    changes = ChangeDetector._compare_files(baseline_files=[dict(BASE_FILE)], scan_files=[modified])
    assert len(changes) == 1
    assert changes[0]["type"] == "modified"
    assert changes[0]["severity"] == "medium"
    assert changes[0]["changes"] == {"hash": {"old": "abc", "new": "newhash"}}


def test_compare_files_no_changes_for_identical_state():
    changes = ChangeDetector._compare_files(baseline_files=[dict(BASE_FILE)], scan_files=[dict(BASE_FILE)])
    assert changes == []


def test_compare_files_handles_mixed_created_modified_deleted_together():
    unchanged = {"path": "/etc/hosts", "hash": "x", "permissions": "644", "owner": "root", "group": "root", "size": 10}
    deleted_file = {"path": "/etc/old-config", "hash": "y", "permissions": "644", "owner": "root", "group": "root", "size": 20}
    modified_before = {"path": "/etc/passwd", "hash": "abc", "permissions": "644", "owner": "root", "group": "root", "size": 100}
    modified_after = {**modified_before, "hash": "changed"}
    created_file = {"path": "/etc/new-file", "hash": "z", "permissions": "600", "owner": "root", "group": "root", "size": 5}

    baseline_files = [unchanged, deleted_file, modified_before]
    scan_files = [unchanged, modified_after, created_file]

    changes = ChangeDetector._compare_files(baseline_files, scan_files)
    changes_by_path = {c["path"]: c for c in changes}

    assert len(changes) == 3
    assert changes_by_path["/etc/old-config"]["type"] == "deleted"
    assert changes_by_path["/etc/passwd"]["type"] == "modified"
    assert changes_by_path["/etc/new-file"]["type"] == "created"
    assert "/etc/hosts" not in changes_by_path  # unchanged file must not appear


# ── _check_whitelist_match ────────────────────────────────────────────────

def test_whitelist_path_rule_exact_match_only():
    rule = make_rule("path", "/etc/passwd")
    assert ChangeDetector._check_whitelist_match("/etc/passwd", rule) is True
    assert ChangeDetector._check_whitelist_match("/etc/passwd.bak", rule) is False


def test_whitelist_glob_rule_matches_pattern():
    rule = make_rule("glob", "/var/log/*.log")
    assert ChangeDetector._check_whitelist_match("/var/log/app.log", rule) is True
    assert ChangeDetector._check_whitelist_match("/var/log/app.txt", rule) is False


def test_whitelist_regex_rule_matches_from_start():
    rule = make_rule("regex", r"^/tmp/.*\.tmp$")
    assert ChangeDetector._check_whitelist_match("/tmp/foo.tmp", rule) is True
    assert ChangeDetector._check_whitelist_match("/opt/tmp/foo.tmp", rule) is False


def test_whitelist_regex_uses_match_not_fullmatch():
    # re.match anchors at the start only, not the end — a pattern without a
    # trailing $ will match any path that merely *starts* with it. This
    # documents actual current behavior (not necessarily ideal behavior),
    # so a future change to fullmatch is a deliberate choice, not a silent one.
    rule = make_rule("regex", r"/etc/passwd")
    assert ChangeDetector._check_whitelist_match("/etc/passwd.bak", rule) is True


def test_whitelist_invalid_regex_fails_closed_not_crash():
    rule = make_rule("regex", "(unclosed[")
    assert ChangeDetector._check_whitelist_match("/etc/passwd", rule) is False


def test_whitelist_unknown_rule_type_returns_false():
    rule = make_rule("something-else", "/etc/passwd")
    assert ChangeDetector._check_whitelist_match("/etc/passwd", rule) is False

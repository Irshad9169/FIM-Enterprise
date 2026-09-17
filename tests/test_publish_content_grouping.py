"""
Confirms _build_publish_content (app/services/ticket_linker.py) actually
uses the report_grouping module -- the RT-published report must show the
same category-bucket/host-clubbing/directory-rollup grouping the report UI
does, not a flat per-file list. See tests/test_report_grouping.py for
thorough coverage of the grouping algorithm itself.
"""
from app.services.ticket_linker import TicketLinkerService


def _change(path, ctype="added", **kw):
    d = {
        "file_path": path, "change_type": ctype, "severity": "medium",
        "baseline_hash": None, "current_hash": "x", "baseline_size": None,
        "current_size": 1, "analyst_notes": None, "is_known_change": False,
        "requires_investigation": False, "baseline_mtime": None,
        "current_mtime": "2026-09-17T10:00:00", "audit_uid": None,
        "audit_process": None, "audit_command": None,
    }
    d.update(kw)
    return d


def _agent(hostname, changes, **kw):
    d = {
        "agent_hostname": hostname, "correlated_rt": None, "correlated_cmr": None,
        "manual_rt": None, "correlation_note": None, "status": "correlated",
        "change_count": len(changes), "changes": changes,
    }
    d.update(kw)
    return d


def test_hosts_with_identical_changes_are_clubbed_in_published_content():
    shared_changes = [_change(f"/usr/lib/modules/mod{i}.ko") for i in range(5)]
    agents_data = [
        _agent("bsa01.int.untd.com", shared_changes),
        _agent("bsa02.int.untd.com", shared_changes),
        _agent("web01.int.untd.com", [_change("/etc/httpd.conf", ctype="changed")]),
    ]
    content = TicketLinkerService._build_publish_content("2026-09-17", agents_data)

    assert "IDENTICAL CHANGES · 2 hosts" in content
    assert "bsa01.int.untd.com" in content
    assert "bsa02.int.untd.com" in content
    # web01 didn't share the change set -- must appear as its own solo host,
    # not folded into the clubbed group.
    assert "HOST: web01.int.untd.com" in content


def test_large_added_batch_is_bucketed_not_listed_flat():
    # The whole point of this feature: a report with hundreds of changed
    # files must not print hundreds of individual file lines.
    changes = [_change(f"/usr/lib/modules/mod{i}.ko") for i in range(300)]
    agents_data = [_agent("bsa01.int.untd.com", changes)]
    content = TicketLinkerService._build_publish_content("2026-09-17", agents_data)

    assert "300 kernel related files were added" in content
    assert "+ 296 more" in content
    # Must not contain all 300 individual file paths.
    assert content.count("/usr/lib/modules/mod") < 20


def test_config_file_change_gets_individual_detail_treatment():
    changes = [_change(
        "/etc/httpd/conf/httpd.conf", ctype="changed",
        baseline_mtime="2026-09-16T09:00:00", current_mtime="2026-09-17T09:05:00",
    )]
    agents_data = [_agent("web01.int.untd.com", changes)]
    content = TicketLinkerService._build_publish_content("2026-09-17", agents_data)

    assert "DETAILED CHANGES" in content
    assert "/etc/httpd/conf/httpd.conf" in content
    assert "2026-09-16T09:00:00 -> 2026-09-17T09:05:00" in content


def test_rejected_correlation_is_not_silently_reattached_in_grouped_output():
    # Same bug class as the earlier RT-correlation-reject fix -- must hold
    # under the new grouped rendering path too.
    changes = [_change("/etc/httpd.conf", ctype="changed")]
    agents_data = [_agent(
        "web01.int.untd.com", changes,
        manual_rt="", correlated_rt="999999",  # explicitly rejected auto-match
    )]
    content = TicketLinkerService._build_publish_content("2026-09-17", agents_data)

    assert "RT Ticket     : N/A" in content
    assert "999999" not in content

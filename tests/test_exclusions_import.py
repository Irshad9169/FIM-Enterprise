"""
Unit tests for app/api/exclusions.py's import-file hardening.

Security review (2026-09) flagged /api/v1/exclusions/import as the only
file-upload endpoint in the app. It never wrote uploaded bytes to disk (so
it was never exposed to the "uploaded web shell becomes reachable" class of
vulnerability), but it had no allow-list, no size cap, and crashed with an
unhandled 500 on any non-UTF-8 upload. These tests cover validate_import_upload(),
the pure helper pulled out of the route so it's testable without a DB session
or a real UploadFile.
"""
import pytest
from fastapi import HTTPException

from app.api.exclusions import validate_import_upload, _MAX_IMPORT_SIZE_BYTES


def test_accepts_txt_extension_and_plain_text_content_type():
    validate_import_upload("exclusions.txt", "text/plain", b"*.log\nregex:^/tmp/.*")


def test_accepts_extensionless_filename():
    validate_import_upload("exclusions", "application/octet-stream", b"*.log")


def test_accepts_missing_filename_and_content_type():
    validate_import_upload(None, None, b"*.log")


def test_rejects_disallowed_extension():
    with pytest.raises(HTTPException) as exc_info:
        validate_import_upload("shell.php", "application/octet-stream", b"<?php system($_GET['c']); ?>")
    assert exc_info.value.status_code == 400


def test_rejects_disallowed_content_type():
    with pytest.raises(HTTPException) as exc_info:
        validate_import_upload("exclusions.txt", "application/x-msdownload", b"*.log")
    assert exc_info.value.status_code == 400


def test_rejects_oversized_content():
    oversized = b"a" * (_MAX_IMPORT_SIZE_BYTES + 1)
    with pytest.raises(HTTPException) as exc_info:
        validate_import_upload("exclusions.txt", "text/plain", oversized)
    assert exc_info.value.status_code == 413


def test_rejects_binary_content_with_null_bytes():
    with pytest.raises(HTTPException) as exc_info:
        validate_import_upload("exclusions.txt", "text/plain", b"MZ\x00\x00binary-not-text")
    assert exc_info.value.status_code == 400

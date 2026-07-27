"""
Unit tests for app/core/security.py — password hashing, JWT creation, and
the input-validation helpers. No database, no network, no FastAPI app
required: these are all pure functions.
"""
from datetime import timedelta

import pytest
from jose import jwt

from app.core import security


# ── Password hashing ─────────────────────────────────────────────────────

def test_password_hash_and_verify_roundtrip():
    hashed = security.get_password_hash("CorrectHorseBattery9!")
    assert security.verify_password("CorrectHorseBattery9!", hashed) is True


def test_password_verify_rejects_wrong_password():
    hashed = security.get_password_hash("CorrectHorseBattery9!")
    assert security.verify_password("WrongPassword123!", hashed) is False


def test_password_hash_is_not_the_plaintext():
    hashed = security.get_password_hash("CorrectHorseBattery9!")
    assert hashed != "CorrectHorseBattery9!"


def test_password_verify_handles_garbage_hash_gracefully():
    # A malformed "hash" (e.g. corrupted DB row) must not raise — it should
    # fail closed (return False), not crash the request.
    assert security.verify_password("anything", "not-a-real-bcrypt-hash") is False


# ── JWT creation ──────────────────────────────────────────────────────────

def _decode(token: str) -> dict:
    """Decode using the same secret/algorithm the module itself uses."""
    return jwt.decode(
        token, security.SECRET_KEY, algorithms=[security.ALGORITHM],
        options={"require_exp": True},
    )


def test_create_access_token_contains_expected_claims():
    token = security.create_access_token(
        {"sub": "user-123", "username": "alice", "role": "analyst"}
    )
    payload = _decode(token)

    assert payload["sub"] == "user-123"
    assert payload["username"] == "alice"
    assert payload["role"] == "analyst"
    assert payload["iss"] == security.TOKEN_ISSUER
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_create_access_token_jti_is_unique_per_call():
    token_a = security.create_access_token({"sub": "user-123"})
    token_b = security.create_access_token({"sub": "user-123"})
    assert _decode(token_a)["jti"] != _decode(token_b)["jti"]


def test_create_access_token_respects_custom_expiry():
    token = security.create_access_token(
        {"sub": "user-123"}, expires_delta=timedelta(minutes=5)
    )
    payload = _decode(token)
    assert payload["exp"] - payload["iat"] == pytest.approx(5 * 60, abs=2)


def test_create_access_token_default_expiry_matches_configured_minutes():
    token = security.create_access_token({"sub": "user-123"})
    payload = _decode(token)
    expected_seconds = security.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert payload["exp"] - payload["iat"] == pytest.approx(expected_seconds, abs=2)


def test_expired_token_fails_decode():
    token = security.create_access_token(
        {"sub": "user-123"}, expires_delta=timedelta(minutes=-1)
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        _decode(token)


def test_token_signed_with_different_secret_is_rejected():
    token = security.create_access_token({"sub": "user-123"})
    with pytest.raises(jwt.JWTError):
        jwt.decode(token, "a-completely-different-secret", algorithms=[security.ALGORITHM])


# ── Password policy validation ──────────────────────────────────────────

@pytest.mark.parametrize("password", [
    "Str0ng!Passw0rd",
    "C0rrect-Horse-Battery",
    "Tr0ub4dor&3xtra!!",
])
def test_password_policy_accepts_strong_passwords(password):
    is_valid, _ = security.validate_password_policy(password)
    assert is_valid is True


def test_password_policy_rejects_too_short():
    is_valid, msg = security.validate_password_policy("Sh0rt!")
    assert is_valid is False
    assert "12 characters" in msg


def test_password_policy_rejects_too_long():
    is_valid, msg = security.validate_password_policy("A1!" + "a" * 130)
    assert is_valid is False
    assert "128 characters" in msg


def test_password_policy_requires_uppercase():
    is_valid, msg = security.validate_password_policy("nouppercase123!")
    assert is_valid is False
    assert "uppercase" in msg


def test_password_policy_requires_lowercase():
    is_valid, msg = security.validate_password_policy("NOLOWERCASE123!")
    assert is_valid is False
    assert "lowercase" in msg


def test_password_policy_requires_digit():
    is_valid, msg = security.validate_password_policy("NoDigitsHere!!")
    assert is_valid is False
    assert "number" in msg


def test_password_policy_requires_special_char():
    is_valid, msg = security.validate_password_policy("NoSpecialChar123")
    assert is_valid is False
    assert "special character" in msg


def test_password_policy_rejects_known_weak_password():
    # "password123" is both too short and in the common-password list —
    # either reason is sufficient for this to fail the policy.
    is_valid, _ = security.validate_password_policy("password123")
    assert is_valid is False


def test_password_policy_baseline_valid_password_sanity_check():
    # Confirms a password shaped to satisfy every rule actually passes,
    # so the rejection tests above are meaningfully testing each rule
    # rather than everything failing regardless of input.
    is_valid, msg = security.validate_password_policy("Str0ngPassw0rd!")
    assert is_valid is True
    assert msg == "Password meets policy requirements"


# ── File path validation ─────────────────────────────────────────────────

def test_validate_file_path_accepts_normal_absolute_path():
    assert security.validate_file_path("/etc/passwd") == "/etc/passwd"


@pytest.mark.parametrize("bad_path", [
    "",
    "relative/path",
    "/etc/../etc/passwd",
    "/etc/passwd\x00.jpg",
    "/etc/$(whoami)",
    "/etc/foo;rm -rf /",
])
def test_validate_file_path_rejects_dangerous_input(bad_path):
    with pytest.raises(ValueError):
        security.validate_file_path(bad_path)


def test_validate_file_path_rejects_too_long():
    with pytest.raises(ValueError):
        security.validate_file_path("/" + "a" * 5000)


# ── Hostname validation ───────────────────────────────────────────────────

@pytest.mark.parametrize("hostname", [
    "test06.hyd.int.untd.com",
    "web-server-01",
    "a.b.c",
])
def test_validate_hostname_accepts_valid_hostnames(hostname):
    assert security.validate_hostname(hostname) == hostname


@pytest.mark.parametrize("bad_hostname", [
    "",
    "host;name",
    "host with spaces",
    "-starts-with-hyphen",
    "ends-with-hyphen-",
])
def test_validate_hostname_rejects_invalid_hostnames(bad_hostname):
    with pytest.raises(ValueError):
        security.validate_hostname(bad_hostname)


def test_validate_hostname_rejects_consecutive_dots():
    with pytest.raises(ValueError):
        security.validate_hostname("host..example.com")


def test_validate_hostname_rejects_consecutive_hyphens():
    with pytest.raises(ValueError):
        security.validate_hostname("host--example.com")


# ── Pattern validation ───────────────────────────────────────────────────

def test_validate_pattern_regex_accepts_valid_regex():
    assert security.validate_pattern(r"^/tmp/.*\.log$", "regex") == r"^/tmp/.*\.log$"


def test_validate_pattern_regex_rejects_invalid_regex():
    with pytest.raises(ValueError):
        security.validate_pattern("(unclosed", "regex")


def test_validate_pattern_glob_rejects_shell_metacharacters():
    with pytest.raises(ValueError):
        security.validate_pattern("/tmp/$(whoami)/*", "glob")


def test_validate_pattern_unknown_type_rejected():
    with pytest.raises(ValueError):
        security.validate_pattern("/tmp/*", "not-a-real-type")


# ── String sanitization ───────────────────────────────────────────────────

def test_sanitize_string_strips_whitespace():
    assert security.sanitize_string("  hello  ") == "hello"


def test_sanitize_string_rejects_null_byte():
    with pytest.raises(ValueError):
        security.sanitize_string("hello\x00world")


def test_sanitize_string_rejects_control_characters():
    with pytest.raises(ValueError):
        security.sanitize_string("hello\x07world")


def test_sanitize_string_allows_newline_and_tab():
    assert security.sanitize_string("line1\nline2\ttabbed") == "line1\nline2\ttabbed"


def test_sanitize_string_enforces_max_length():
    with pytest.raises(ValueError):
        security.sanitize_string("a" * 300, max_length=255)

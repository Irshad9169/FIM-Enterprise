"""
Shared test fixtures.

Everything here uses plain stub objects (types.SimpleNamespace) instead of
real SQLAlchemy models or a database connection. The functions under test
in security.py, change_detector.py, and rbac.py only ever *read attributes*
off the objects they're given — they never issue queries themselves — so a
stub with the right attributes behaves identically to a real ORM instance
for these tests, with no database required.
"""
from types import SimpleNamespace

import pytest


@pytest.fixture
def make_user():
    """Factory for a fake authenticated user with a given role."""
    def _make(role: str, is_active: bool = True):
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000001",
            username="testuser",
            role=role,
            is_active=is_active,
        )
    return _make

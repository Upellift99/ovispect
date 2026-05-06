"""Unit tests for the auth module (verify_password, rate limiter, helpers)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ovispect.auth import (
    LoginRateLimiter,
    build_login_redirect,
    is_auth_enabled,
    is_safe_next,
    verify_password,
)
from ovispect.config import Settings
from tests.conftest import PLAIN_PASSWORD, make_bcrypt_hash


def test_verify_password_accepts_correct_password() -> None:
    h = make_bcrypt_hash()
    assert verify_password(PLAIN_PASSWORD, h) is True


def test_verify_password_rejects_wrong_password() -> None:
    h = make_bcrypt_hash()
    assert verify_password("nope", h) is False


def test_verify_password_returns_false_on_malformed_hash() -> None:
    assert verify_password(PLAIN_PASSWORD, "definitely-not-a-bcrypt-hash") is False


def test_verify_password_returns_false_on_empty_hash() -> None:
    assert verify_password(PLAIN_PASSWORD, "") is False


def test_is_auth_enabled_false_for_empty_hash() -> None:
    s = Settings(openvpn_host="127.0.0.1", openvpn_port=5555)
    assert is_auth_enabled(s) is False


def test_is_auth_enabled_true_for_configured_hash() -> None:
    s = Settings(
        openvpn_host="127.0.0.1",
        openvpn_port=5555,
        auth_password_hash=make_bcrypt_hash(),
        session_secret="x" * 64,
    )
    assert is_auth_enabled(s) is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/", True),
        ("/dashboard", True),
        ("/path?with=query", True),
        ("", False),
        (None, False),
        ("relative-path", False),
        ("//evil.com/path", False),
        ("https://evil.com", False),
    ],
)
def test_is_safe_next(value: str | None, expected: bool) -> None:
    assert is_safe_next(value) is expected


def test_build_login_redirect_includes_safe_next() -> None:
    assert build_login_redirect("/dashboard") == "/login?next=/dashboard"


def test_build_login_redirect_drops_unsafe_next() -> None:
    assert build_login_redirect("//evil.com") == "/login"
    assert build_login_redirect(None) == "/login"


class TestLoginRateLimiter:
    def setup_method(self) -> None:
        self.now = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
        self.limiter = LoginRateLimiter(
            max_attempts=5,
            window=timedelta(minutes=5),
            lockout=timedelta(minutes=5),
        )

    def test_allows_initial_attempts(self) -> None:
        assert self.limiter.check("1.2.3.4", now=self.now).allowed is True

    def test_blocks_after_max_failures_within_window(self) -> None:
        for i in range(5):
            self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(seconds=i))
        decision = self.limiter.check("1.2.3.4", now=self.now + timedelta(seconds=10))
        assert decision.allowed is False
        assert decision.retry_after is not None
        assert decision.retry_after <= timedelta(minutes=5)

    def test_releases_lockout_after_cooldown(self) -> None:
        for i in range(5):
            self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(seconds=i))
        later = self.now + timedelta(minutes=10)
        assert self.limiter.check("1.2.3.4", now=later).allowed is True

    def test_reset_clears_failures(self) -> None:
        for i in range(5):
            self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(seconds=i))
        self.limiter.reset("1.2.3.4")
        assert self.limiter.check("1.2.3.4", now=self.now + timedelta(seconds=10)).allowed is True

    def test_independent_per_ip(self) -> None:
        for i in range(5):
            self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(seconds=i))
        assert self.limiter.check("5.6.7.8", now=self.now).allowed is True

    def test_old_failures_age_out_of_window(self) -> None:
        # 4 failures right at start, then a 6-minute gap
        for i in range(4):
            self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(seconds=i))
        # ... and one fresh failure outside the window. Should still allow.
        self.limiter.register_failure("1.2.3.4", now=self.now + timedelta(minutes=10))
        decision = self.limiter.check("1.2.3.4", now=self.now + timedelta(minutes=10))
        assert decision.allowed is True

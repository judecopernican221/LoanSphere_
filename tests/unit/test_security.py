import pytest
from app.core.security import (
    hash_password, verify_password,
    create_access_token, decode_access_token,
    has_permission, UserRole,
)


class TestPasswords:
    def test_hash_differs_from_plain(self):
        assert hash_password("secret") != "secret"

    def test_correct_password_verifies(self):
        h = hash_password("mypass")
        assert verify_password("mypass", h) is True

    def test_wrong_password_fails(self):
        h = hash_password("mypass")
        assert verify_password("wrong", h) is False

    def test_same_password_different_hashes(self):
        # bcrypt salts every hash differently
        assert hash_password("abc") != hash_password("abc")


class TestJWT:
    def test_encode_decode_roundtrip(self):
        token = create_access_token("user1", UserRole.ENGINEER)
        payload = decode_access_token(token)
        assert payload["sub"] == "user1"
        assert payload["role"] == "engineer"

    def test_invalid_token_returns_none(self):
        assert decode_access_token("not.a.token") is None

    def test_tampered_token_returns_none(self):
        token = create_access_token("user1", UserRole.ADMIN)
        tampered = token[:-4] + "XXXX"
        assert decode_access_token(tampered) is None

    def test_all_roles_encoded(self):
        for role in UserRole:
            token = create_access_token("u", role)
            payload = decode_access_token(token)
            assert payload["role"] == role.value


class TestRBAC:
    def test_admin_passes_all(self):
        assert has_permission("admin", UserRole.ADMIN)    is True
        assert has_permission("admin", UserRole.ENGINEER) is True
        assert has_permission("admin", UserRole.VIEWER)   is True

    def test_engineer_not_admin(self):
        assert has_permission("engineer", UserRole.ADMIN)    is False
        assert has_permission("engineer", UserRole.ENGINEER) is True
        assert has_permission("engineer", UserRole.VIEWER)   is True

    def test_viewer_only_viewer(self):
        assert has_permission("viewer", UserRole.ADMIN)    is False
        assert has_permission("viewer", UserRole.ENGINEER) is False
        assert has_permission("viewer", UserRole.VIEWER)   is True

    def test_unknown_role_denied(self):
        assert has_permission("hacker", UserRole.VIEWER) is False

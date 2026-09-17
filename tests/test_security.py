from app.config import Settings
from app.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hash_and_jwt_round_trip():
    encoded = hash_password("Secret123!")
    assert verify_password("Secret123!", encoded)
    assert not verify_password("wrong", encoded)

    settings = Settings(_env_file=None, jwt_secret="a-secure-test-secret-with-more-than-32-chars")
    token, expires_at = create_access_token(subject="agent-1", settings=settings)
    payload = decode_access_token(token, settings)

    assert payload["sub"] == "agent-1"
    assert payload["exp"] == int(expires_at.timestamp())

from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache
def get_fernet() -> Fernet:
    return Fernet(get_settings().fernet_key)


def encrypt(data: bytes) -> bytes:
    return get_fernet().encrypt(data)


def decrypt(token: bytes) -> bytes:
    return get_fernet().decrypt(token)

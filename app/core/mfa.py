"""
MFA Service — GAP #20
TOTP via pyotp, secret encrypted with Fernet before DB storage.
"""
import os, base64, io
import pyotp
import qrcode
from cryptography.fernet import Fernet

# Derive a stable Fernet key from the app SECRET_KEY
def _get_fernet() -> Fernet:
    secret = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
    # Fernet needs exactly 32 url-safe base64 bytes
    raw = secret.encode()[:32].ljust(32, b'0')
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)

def encrypt_secret(plain: str) -> str:
    return _get_fernet().encrypt(plain.encode()).decode()

def decrypt_secret(encrypted: str) -> str:
    return _get_fernet().decrypt(encrypted.encode()).decode()

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def get_totp_uri(secret: str, username: str, issuer: str = "FIM Enterprise") -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username, issuer_name=issuer
    )

def generate_qr_base64(secret: str, username: str) -> str:
    uri = get_totp_uri(secret, username)
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

def verify_totp(encrypted_secret: str, code: str) -> bool:
    try:
        secret = decrypt_secret(encrypted_secret)
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)  # ±30s drift
    except Exception:
        return False

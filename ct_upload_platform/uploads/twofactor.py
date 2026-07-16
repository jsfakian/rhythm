"""
TOTP (authenticator app) helpers for two-factor login.
"""

import base64
from io import BytesIO

import pyotp
import qrcode
import qrcode.image.svg
from django.contrib.auth.models import User

ISSUER_NAME = 'RHYTHM Repository'


def generate_secret() -> str:
    """Return a new random base32 TOTP secret."""
    return pyotp.random_base32()


def verify_code(secret: str, code: str) -> bool:
    """Check *code* against *secret*, allowing for one step of clock drift."""
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def provisioning_uri(user: User, secret: str) -> str:
    """Return the otpauth:// URI an authenticator app scans to add the account."""
    return pyotp.TOTP(secret).provisioning_uri(
        name=user.username, issuer_name=ISSUER_NAME,
    )


def qr_code_data_uri(uri: str) -> str:
    """Render *uri* as an SVG QR code, returned as a base64 data: URI."""
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgImage)
    buf = BytesIO()
    img.save(buf)
    encoded = base64.b64encode(buf.getvalue()).decode('ascii')
    return f'data:image/svg+xml;base64,{encoded}'

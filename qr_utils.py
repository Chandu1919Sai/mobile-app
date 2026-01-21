import qrcode
import base64
from io import BytesIO

def generate_qr(token: str):
    qr = qrcode.make(token)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()

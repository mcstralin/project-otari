import base64

def encode_attachment(data: bytes) -> str:
    """MIME-style base64 with line breaks."""
    return base64.encodebytes(data).decode("ascii")

def decode_attachment(text: str) -> bytes:
    return base64.decodebytes(text.encode("ascii"))

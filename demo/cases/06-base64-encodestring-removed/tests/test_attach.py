from codec.attach import decode_attachment, encode_attachment

def test_roundtrip():
    blob = b"hello otari " * 20
    assert decode_attachment(encode_attachment(blob)) == blob

def test_has_line_breaks():
    assert "\n" in encode_attachment(b"x" * 200)

"""
Part B: verify X-PseudoGram-Signature.

The README is explicit that the signature is HMAC-SHA256 of the RAW
request body, using the API key as the secret. That means we must
compute the HMAC over the exact bytes FastAPI received -- not over a
re-serialized `json.dumps(parsed_body)`, which can differ in key order,
whitespace, or unicode escaping and would make every signature check
fail. We read `await request.body()` before any JSON parsing happens.
"""
import hashlib
import hmac


def compute_signature(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def is_valid_signature(raw_body: bytes, header_value: str | None, secret: str) -> bool:
    if not header_value:
        return False
    expected = compute_signature(raw_body, secret)
    # constant-time comparison to avoid leaking the correct signature
    # one byte at a time via response-time side channels
    return hmac.compare_digest(expected, header_value)

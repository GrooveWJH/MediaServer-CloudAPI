import hashlib
import hmac
from datetime import datetime, timezone


def _aws_v4_sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _aws_v4_signature(secret_key, date_stamp, region, service, string_to_sign):
    k_date = _aws_v4_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()
    return hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def aws_v4_headers(access_key, secret_key, region, service, method, host, canonical_uri, payload, extra_headers=None):
    extra_headers = extra_headers or {}
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    payload_hash = hashlib.sha256(payload).hexdigest()

    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    for key, value in extra_headers.items():
        headers[key.lower()] = value

    signed_headers = ";".join(sorted(headers.keys()))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers.keys()))
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = _aws_v4_signature(secret_key, date_stamp, region, service, string_to_sign)
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )

    headers["authorization"] = authorization
    return headers

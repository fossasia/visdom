# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import hashlib
import hmac
import os
import time

MAX_SKEW_SECONDS = 60

READ = "read"
ADMIN = "admin"

KEY_VARIABLES = {
    READ: "VISDOM_INTERNAL_READ_KEYS",
    ADMIN: "VISDOM_INTERNAL_ADMIN_KEYS",
}
METRICS_TOKEN_VARIABLE = "VISDOM_METRICS_TOKENS"

TIMESTAMP_HEADER = "X-Visdom-Timestamp"
SIGNATURE_HEADER = "X-Visdom-Signature"


def configured(variable):
    return [
        value.strip()
        for value in os.environ.get(variable, "").split(",")
        if value.strip()
    ]


def signature(key, method, uri, timestamp, body):
    message = "\n".join(
        [
            method.upper(),
            uri,
            str(timestamp),
            hashlib.sha256(body or b"").hexdigest(),
        ]
    )
    return hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def signed_headers(key, method, uri, body=b"", now=None):
    timestamp = int(time.time() if now is None else now)
    return {
        TIMESTAMP_HEADER: str(timestamp),
        SIGNATURE_HEADER: signature(key, method, uri, timestamp, body),
    }


def is_signed(request, scope, now=None):
    keys = configured(KEY_VARIABLES[scope])
    timestamp = request.headers.get(TIMESTAMP_HEADER, "")
    given = request.headers.get(SIGNATURE_HEADER, "")
    if not keys or not timestamp.isdigit() or not given:
        return False
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > MAX_SKEW_SECONDS:
        return False
    return any(
        hmac.compare_digest(
            signature(key, request.method, request.uri, timestamp, request.body),
            given,
        )
        for key in keys
    )


def has_metrics_token(request):
    tokens = configured(METRICS_TOKEN_VARIABLE)
    header = request.headers.get("Authorization", "")
    if not tokens or not header.startswith("Bearer "):
        return False
    given = header[len("Bearer ") :]
    return any(hmac.compare_digest(token, given) for token in tokens)

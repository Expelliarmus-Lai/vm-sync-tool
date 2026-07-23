"""Shared decoding for vmrun and guest-process output."""

from __future__ import annotations

import locale


def decode_vmrun_stream(value) -> str:
    """Decode vmrun bytes, preferring guest UTF encodings with host fallback."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    raw = bytes(value)
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    preferred = locale.getpreferredencoding(False) or "mbcs"
    for encoding in dict.fromkeys((preferred, "mbcs", "gb18030")):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode(preferred, errors="replace")


def decode_vmrun_result(result):
    result.stdout = decode_vmrun_stream(getattr(result, "stdout", None))
    result.stderr = decode_vmrun_stream(getattr(result, "stderr", None))
    return result

"""HTTP Range header parsing (RFC 9110 §14), single-range only."""

import re

from app.core.errors import AppError

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeNotSatisfiable(AppError):
    status_code = 416
    code = "range_not_satisfiable"


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Return an inclusive (start, end) byte range, or None to serve the whole file.

    Multi-range and malformed headers fall back to a full response, which RFC 9110 permits.
    """
    if not header:
        return None
    match = _RANGE.match(header.strip())
    if not match:
        return None
    first, last = match.groups()
    if first == "" and last == "":
        return None
    if first == "":  # suffix range: last N bytes
        length = int(last)
        if length == 0:
            raise RangeNotSatisfiable("Range not satisfiable", details={"size": size})
        return max(0, size - length), size - 1
    start = int(first)
    end = int(last) if last else size - 1
    if start >= size or end < start:
        raise RangeNotSatisfiable("Range not satisfiable", details={"size": size})
    return start, min(end, size - 1)

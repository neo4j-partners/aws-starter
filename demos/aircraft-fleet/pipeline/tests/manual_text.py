"""Helpers the manual tests share for reading a manual's text."""

from __future__ import annotations

import re

# A numbered section heading, such as "### 4.1 Overheat".
_NUMBERED_HEADING = re.compile(r"#{3,5} \d")
# Any line that starts like a fault code field, in any case, emphasis, list
# marker, or separator, so a variant cannot slip past the strict form.
_LOOSE_FAULT_CODE = re.compile(r"^\W*\**\s*fault[\s_-]*codes?\b", re.IGNORECASE)
_FAULT_CODE = re.compile(r"\*\*Fault Code:\*\* (\S+)")


def fault_code_lines(text: str) -> list[tuple[str, str]]:
    """Each "**Fault Code:**" line's code, with the heading above it.

    A line that starts like one in any other form raises, so a variant fails
    a test instead of being skipped.
    """
    out = []
    heading = ""
    for line in text.splitlines():
        if _NUMBERED_HEADING.match(line):
            heading = line.lstrip("# ")
        elif _LOOSE_FAULT_CODE.match(line):
            match = _FAULT_CODE.fullmatch(line)
            if match is None:
                raise ValueError(f"not a plain Fault Code line: {line!r}")
            out.append((match.group(1), heading))
    return out

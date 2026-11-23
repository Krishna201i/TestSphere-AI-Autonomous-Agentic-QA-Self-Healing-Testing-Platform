"""
TestSphere-AI — What the explorer may and may not do on a live site.

The explorer acts on a real application, so every action the model proposes
is checked before it runs:

* only interactions (click, type, choose, tick, hover, a few keys) and
  navigation on the site it started on;
* it types only values written in the goal (a model never invents a
  password or fills a form with made-up data);
* it refuses elements that delete, pay, transfer or end the session, unless
  the goal itself asks for that.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

ACTIONS = frozenset({"click", "fill", "select", "check", "uncheck", "hover", "press", "goto", "done", "give_up"})
ELEMENT_ACTIONS = frozenset({"click", "fill", "select", "check", "uncheck", "hover"})
KEYS = frozenset({"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"})

# Words that mark an element whose action cannot be undone, costs money or
# ends the session the rest of the goal needs
_RISKY = re.compile(
    r"\b(delete|remove|destroy|erase|deactivate|close account|unsubscribe|pay|payment|purchase|buy now|"
    r"place order|checkout|check out|transfer|withdraw|send money|cancel (?:subscription|order|account|booking)|"
    r"log ?out|sign ?out|reset)\b",
    re.IGNORECASE,
)


def risky_reason(label: str, href: str | None, goal: str) -> str | None:
    """Why acting on this element is refused, or None when it is allowed."""
    for text in (label or "", href or ""):
        match = _RISKY.search(text)
        if match and match.group(1).lower() not in goal.lower():
            return f'"{(label or href or "")[:60]}" looks like it would {match.group(1).lower()}; the goal does not ask for that'
    return None


def typed_value_reason(value: str | None, allowed: set[str]) -> str | None:
    """Why typing *value* is refused: only values written in the goal may be typed."""
    if not value:
        return "nothing to type"
    if value not in allowed:
        return ("only values written in the goal may be typed"
                + (f" ({', '.join(sorted(repr(v) for v in allowed))})" if allowed else "; the goal gives none"))
    return None


def same_site(start_url: str, url: str) -> bool:
    """Whether *url* (absolute or relative to *start_url*) stays on the site the explorer started on."""
    target = urlsplit(urljoin(start_url, url))
    return target.scheme in ("http", "https") and target.hostname == urlsplit(start_url).hostname

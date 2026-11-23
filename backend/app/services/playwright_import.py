"""
TestSphere-AI — Import Playwright tests as TestSphere tests.

Reads ``*.spec.ts`` / ``*.spec.js`` / ``*.test.ts`` files **as text** and turns
each ``test('name', async ({ page }) => { ... })`` into stored steps that the
engine runs and self-heals.  Nothing in the file is executed: a statement this
reader does not understand (a helper call, a loop, a value from a variable or
``process.env``) is listed as not imported, never guessed.

Locators keep Playwright's own meaning: ``getByRole('button', { name: 'Log in' })``
becomes the selector ``internal:role=button[name="Log in"i]``, the same one
Playwright compiles it to, so an imported step finds the element the original did.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 200_000
MAX_TESTS = 50

_TEST_START = re.compile(
    r"""\btest(?:\.only)?\s*\(\s*(?P<q>['"`])(?P<name>(?:\\.|(?!(?P=q)).)*)(?P=q)\s*,\s*async\s*(?:function\s*)?\(\s*\{[^}]*\}[^)]*\)\s*(?:=>\s*)?\{""",
    re.DOTALL)
_SKIPPED = re.compile(r"\btest\.(?:skip|fixme)\s*\(")
_STRING = r"""(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\$])*`)"""


def _unquote(token: str) -> str | None:
    """A JS string literal's value; None for anything else (a variable, a template with ${})."""
    token = token.strip()
    if len(token) < 2 or token[0] not in "'\"`" or token[-1] != token[0]:
        return None
    body = token[1:-1]
    if token[0] == "`" and "${" in body:
        return None
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


def _block(text: str, start: int) -> tuple[str, int]:
    """The body of the block whose ``{`` is just before *start*, and the index after its ``}``."""
    depth, i, quote = 1, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif text.startswith("//", i):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return text[start:], len(text)


def _statements(body: str) -> list[str]:
    """Top-level statements of a block (split on ; and newlines outside brackets and strings)."""
    out, cur, depth, quote, i = [], [], 0, None, 0
    while i < len(body):
        c = body[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(body):
                cur.append(body[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            cur.append(c)
        elif body.startswith("//", i):
            nl = body.find("\n", i)
            i = len(body) if nl < 0 else nl
            continue
        elif body.startswith("/*", i):
            end = body.find("*/", i + 2)
            i = len(body) if end < 0 else end + 2
            continue
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif depth == 0 and c in ";\n":
            stmt = "".join(cur).strip()
            if stmt:
                out.append(stmt)
            cur = []
        else:
            cur.append(c)
        i += 1
    stmt = "".join(cur).strip()
    if stmt:
        out.append(stmt)
    # A chain continued on the next line (".click()") belongs to the statement before it
    merged: list[str] = []
    for s in out:
        if merged and s.startswith("."):
            merged[-1] += s
        else:
            merged.append(s)
    return merged


def _args(text: str) -> list[str]:
    """Top-level comma-separated arguments of a call's argument list."""
    out, cur, depth, quote = [], [], 0, None
    for i, c in enumerate(text):
        if quote:
            cur.append(c)
            if c == quote and text[i - 1] != "\\":
                quote = None
            continue
        if c in "'\"`":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _calls(chain: str) -> list[tuple[str, str]] | None:
    """``a.b(x).c(y)`` -> [("b", "x"), ("c", "y")] after the leading object; None when not a plain chain."""
    calls, i = [], 0
    while i < len(chain):
        m = re.match(r"\s*\.\s*([A-Za-z_]\w*)\s*", chain[i:])
        if not m:
            return None
        name = m.group(1)
        i += m.end()
        if i < len(chain) and chain[i] == "(":
            depth, j, quote = 0, i, None
            while j < len(chain):
                c = chain[j]
                if quote:
                    if c == quote and chain[j - 1] != "\\":
                        quote = None
                elif c in "'\"`":
                    quote = c
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            calls.append((name, chain[i + 1:j]))
            i = j + 1
        else:
            calls.append((name, None))  # a property (keyboard, not)
    return calls


def _option(obj: str, key: str) -> str | bool | None:
    m = re.search(rf"\b{key}\s*:\s*({_STRING}|true|false)", obj or "")
    if not m:
        return None
    return {"true": True, "false": False}.get(m.group(1), _unquote(m.group(1)))


def _quote_attr(value: str) -> str:
    return json.dumps(value)


def _locator(calls: list[tuple[str, str]], variables: dict[str, str]) -> tuple[str | None, list[tuple[str, str]]]:
    """Build a selector from locator calls at the start of *calls*; returns (selector, the rest)."""
    parts: list[str] = []
    i = 0
    while i < len(calls):
        name, arg = calls[i]
        args = _args(arg) if arg is not None else []
        first = _unquote(args[0]) if args else None
        exact = _option(args[1], "exact") is True if len(args) > 1 else False
        flag = "s" if exact else "i"
        if name == "locator" and first is not None:
            parts.append(first)
        elif name == "getByRole" and first is not None:
            label = _option(args[1], "name") if len(args) > 1 else None
            if len(args) > 1 and label is None and "name" in args[1]:
                return None, calls  # a name from a variable or a regex
            parts.append(f"internal:role={first}" + (f"[name={_quote_attr(label)}{flag}]" if label else ""))
        elif name == "getByText" and first is not None:
            parts.append(f"internal:text={_quote_attr(first)}{flag}")
        elif name == "getByLabel" and first is not None:
            parts.append(f"internal:label={_quote_attr(first)}{flag}")
        elif name == "getByPlaceholder" and first is not None:
            parts.append(f"internal:attr=[placeholder={_quote_attr(first)}{flag}]")
        elif name in ("getByTitle", "getByAltText") and first is not None:
            attr = "title" if name == "getByTitle" else "alt"
            parts.append(f"internal:attr=[{attr}={_quote_attr(first)}{flag}]")
        elif name == "getByTestId" and first is not None:
            parts.append(f"internal:testid=[data-testid={_quote_attr(first)}s]")
        elif name == "first" and parts:
            parts.append("nth=0")
        elif name == "last" and parts:
            parts.append("nth=-1")
        elif name == "nth" and parts and args and args[0].strip().lstrip("-").isdigit():
            parts.append(f"nth={int(args[0])}")
        else:
            break
        i += 1
    if not parts:
        return None, calls
    return " >> ".join(parts), calls[i:]


_ACTIONS = {"click": "CLICK", "dblclick": "CLICK", "tap": "CLICK", "fill": "FILL", "type": "FILL",
            "pressSequentially": "FILL", "press": "PRESS", "check": "CHECK", "uncheck": "UNCHECK", "hover": "HOVER",
            "selectOption": "SELECT"}
_VALUE_ACTIONS = {"FILL", "PRESS", "SELECT"}
_ASSERTS = {"toBeVisible": "ASSERT_VISIBLE", "toBeHidden": "ASSERT_HIDDEN", "toHaveText": "ASSERT_HAS_TEXT",
            "toContainText": "ASSERT_CONTAINS_TEXT", "toHaveValue": "ASSERT_VALUE"}
_NEGATED = {"toBeVisible": "ASSERT_HIDDEN", "toBeHidden": "ASSERT_VISIBLE"}


def _step(action: str, target: str | None = None, value: str | None = None, source: str = "") -> dict[str, Any]:
    return {"action": action, "target": target, "value": value, "description": source[:160]}


def _statement_steps(stmt: str, variables: dict[str, str]) -> list[dict[str, Any]] | None:
    """Steps for one statement; None when it cannot be imported."""
    src = " ".join(stmt.split())
    s = re.sub(r"^await\s+", "", src)

    # const login = page.getByRole('button', { name: 'Log in' })
    m = re.match(r"^(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:await\s+)?page(\..+)$", s)
    if m:
        calls = _calls(m.group(2))
        selector, rest = _locator(calls or [], variables)
        if selector and not rest:
            variables[m.group(1)] = selector
            return []
        return None

    # expect(...).[not.]toX(...)
    m = re.match(r"^expect\s*\((.*)\)\s*(\..+)$", s)
    if m:
        subject, chain = m.group(1).strip(), _calls(m.group(2))
        if not chain:
            return None
        negated = chain[0][0] == "not"
        if negated:
            chain = chain[1:]
        if len(chain) != 1:
            return None
        matcher, arg = chain[0]
        args = _args(arg or "")
        if subject == "page":
            if matcher == "toHaveURL" and args:
                literal = _unquote(args[0])
                if literal is not None and not negated:
                    return [_step("ASSERT_URL_EQUALS" if re.match(r"^https?://", literal) else "ASSERT_URL",
                                  value=literal, source=src)]
                rx = re.fullmatch(r"/((?:\\.|[^/\\])+)/[a-z]*", args[0].strip())
                if rx and not negated and re.fullmatch(r"[\w\-./]+", rx.group(1).replace("\\/", "/").replace("\\.", ".")):
                    return [_step("ASSERT_URL", value=rx.group(1).replace("\\/", "/").replace("\\.", "."), source=src)]
                return None
            if matcher == "toHaveTitle" and args and not negated:
                literal = _unquote(args[0])
                return None if literal is None else [_step("ASSERT_CONTAINS_TEXT", "head > title", literal, src)]
            return None
        target = variables.get(subject)
        if target is None and subject.startswith("page."):
            target, rest = _locator(_calls(subject[4:]) or [], variables)
            if rest:
                return None
        if target is None:
            return None
        action = _NEGATED.get(matcher) if negated else _ASSERTS.get(matcher)
        if action is None:
            return None
        value = None
        if action in ("ASSERT_HAS_TEXT", "ASSERT_CONTAINS_TEXT", "ASSERT_VALUE"):
            value = _unquote(args[0]) if args else None
            if value is None:
                return None
        return [_step(action, target, value, src)]

    # page.goto / reload / goBack / waitForTimeout / keyboard.press / locator actions
    m = re.match(r"^(page|[A-Za-z_]\w*)(\..+)$", s)
    if not m:
        return None
    calls = _calls(m.group(2))
    if not calls:
        return None
    if m.group(1) != "page":
        if m.group(1) not in variables:
            return None
        target, rest = variables[m.group(1)], calls
    else:
        name, arg = calls[0]
        args = _args(arg or "")
        if name == "goto" and args:
            url = _unquote(args[0])
            return None if url is None else [_step("NAVIGATE", value=url, source=src)]
        if name == "reload":
            return [_step("RELOAD", source=src)]
        if name == "goBack":
            return [_step("GO_BACK", source=src)]
        if name == "waitForTimeout" and args and args[0].strip().isdigit():
            return [_step("WAIT", value=args[0].strip(), source=src)]
        if name in ("waitForLoadState", "waitForURL"):
            return [_step("WAIT", source=src)]
        if name == "keyboard" and len(calls) == 2 and calls[1][0] == "press":
            key = _unquote(_args(calls[1][1] or "")[0]) if calls[1][1] else None
            return None if key is None else [_step("PRESS", value=key, source=src)]
        if name in ("click", "fill", "check", "uncheck", "hover", "selectOption", "press", "type", "dblclick") and args:
            # Old-style page.click('#sel'), page.fill('#sel', 'value')
            sel = _unquote(args[0])
            if sel is None:
                return None
            target, rest = sel, [(name, ", ".join(args[1:]))]
        else:
            target, rest = _locator(calls, variables)
    if not target or len(rest) != 1:
        return None
    name, arg = rest[0]
    action = _ACTIONS.get(name)
    if action is None:
        return None
    value = None
    if action in _VALUE_ACTIONS:
        args = _args(arg or "")
        value = _unquote(args[0]) if args else None
        if value is None:
            return None
    return [_step(action, target, value, src)]


def parse_spec(text: str, filename: str = "spec.ts") -> dict[str, Any]:
    """Every test of a Playwright file as steps, with what could not be imported."""
    text = text[:MAX_FILE_BYTES]
    tests: list[dict[str, Any]] = []
    for m in _TEST_START.finditer(text):
        if len(tests) >= MAX_TESTS:
            break
        body, _ = _block(text, m.end())
        variables: dict[str, str] = {}
        steps: list[dict[str, Any]] = []
        skipped: list[str] = []
        for stmt in _statements(body):
            got = _statement_steps(stmt, variables)
            if got is None:
                skipped.append(" ".join(stmt.split())[:200])
            else:
                steps += got
        name = _unquote(m.group("q") + m.group("name") + m.group("q")) or m.group("name")
        tests.append({"name": name[:120], "file": filename, "steps": steps, "not_imported": skipped})
    return {"file": filename, "tests": tests, "skipped_tests": len(_SKIPPED.findall(text))}


SPEC_FILE = re.compile(r"\.(?:spec|test|e2e)\.(?:ts|js|mjs|cjs|tsx|jsx)$", re.IGNORECASE)


MAX_REPO_SPECS = 40


def repo_specs(root: Path) -> list[dict[str, Any]]:
    """Every Playwright test file under *root* (a checkout), parsed; nothing in it runs.

    Jest or Vitest unit tests that share the ``*.spec.*`` naming are left out,
    as are dependencies and files over ``MAX_FILE_BYTES``.  At most
    ``MAX_REPO_SPECS`` files with tests are returned.
    """
    parsed: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if len(parsed) >= MAX_REPO_SPECS:
            break
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or not SPEC_FILE.search(path.name) or "node_modules/" in rel                 or path.stat().st_size > MAX_FILE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "@playwright/test" not in text and "page." not in text:
            continue  # a Jest or Vitest unit test, not a browser test
        result = parse_spec(text, rel)
        if result["tests"]:
            parsed.append(result)
    return parsed

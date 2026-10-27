# TestSphere MCP server

The MCP server lets a coding agent use TestSphere while it builds an app: run the whole loop on a URL, read
what failed, list security findings and fetch a fix patch. It speaks the Model Context Protocol over stdio, so
it works in Antigravity, Claude Code, Cursor, VS Code, Windsurf and any other MCP client.

It drives a running TestSphere server through its REST API.

| Variable | Meaning |
| --- | --- |
| `TESTSPHERE_URL` | The TestSphere server (default `http://127.0.0.1:8000`) |
| `TESTSPHERE_TOKEN` | An API token, when the server requires sign-in (`AUTH_REQUIRED=true`) |

To get an API token, open the dashboard, go to **Profile → API tokens**, name the token (for example
"Claude Code MCP") and copy it. It starts with `tsk_`, is shown only once, and acts as you until you revoke
it there. Unlike a sign-in session it does not expire after an hour. Deleting your account revokes it.

## Tools

| Tool | What it does |
| --- | --- |
| `test_site` | Runs the loop on a live URL with an optional goal ("log in as ann and add the backpack to the cart") and waits for the result: stages, failed tests with the failing check, parts of the goal that were not tested, security findings |
| `get_run` | The result of a run by id |
| `list_findings` | Open security findings, most severe first, each with its fix |
| `scan_dependencies` | Known vulnerabilities in a repository's pinned dependencies (OSV.dev) |
| `get_fix_patch` | A `git apply`-able patch for a site's open findings, made against its repository |

## Setup

Install TestSphere (`pip install -e .`) and start the server (`python -m uvicorn backend.main:app --port 8000`).
Then add the MCP server to your client.

**Antigravity:** Agent panel → … → MCP Servers → Manage MCP Servers → View raw config, then add:

```json
{
  "mcpServers": {
    "testsphere": {
      "command": "python",
      "args": ["-m", "backend.mcp_server"],
      "cwd": "/path/to/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform",
      "env": { "TESTSPHERE_URL": "http://127.0.0.1:8000" }
    }
  }
}
```

**Cursor:** the same block in `.cursor/mcp.json`. **VS Code:** the same server under `"servers"` in `.vscode/mcp.json`.

**Claude Code:**

```bash
claude mcp add testsphere --env TESTSPHERE_URL=http://127.0.0.1:8000 -- python -m backend.mcp_server
```

With the package installed, `testsphere-mcp` can replace `python -m backend.mcp_server` everywhere.

## Example

> Test http://localhost:3000/login: log in as ann with password pw and add the backpack to the cart.

The agent calls `test_site` and gets back, for example:

```
Run #12 on http://localhost:3000/login: FAILED
Tests: 2/3 passed, 1 failed, 0 self-healed
  FAILED Scenario: log in as ann…: assert_hidden failed: '#password' is still visible
```

It can then fix the code and call `test_site` again until the run passes.

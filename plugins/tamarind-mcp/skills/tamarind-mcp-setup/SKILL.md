---
name: tamarind-mcp-setup
description: Connect, authenticate, or troubleshoot the Tamarind Bio MCP server and run a no-spend connectivity check. Use when Tamarind MCP tools are missing, OAuth is incomplete or rejected, or the user wants MCP rather than the Tamarind CLI. Not for selecting a scientific model or submitting compute.
---

# Connect Tamarind MCP

Use the remote MCP server configured by this plugin. Do not install the Tamarind CLI, request an API key first, or recreate Tamarind HTTP calls.

This plugin ships the server's OAuth client configuration, so a supported client should offer to authorize on first connection rather than failing. Everything below is for when it does not.

## Check availability

Confirm that these server tools are callable:

1. Call `listModalities`.
2. Call `listTags`.
3. Call `getAvailableTools` with a narrow `search` such as `boltz`.
4. Call `getJobSchema` for one returned tool.

These calls do not create jobs or consume compute. Do not call `submitJob` or `submitBatch` as a setup test.

If they succeed, setup is done. There is no separate MCP `auth status` tool; a successful account-scoped catalog call is the connectivity signal.

## Authorize when the tools are missing or unauthorized

Identify which client is running first, then follow only that client's row. Do not read steps for a client the user is not in, and do not offer terminal commands to a user who is not in a terminal client.

| Client | Where to authorize |
| --- | --- |
| Codex app | **Settings → Plugins**, open `tamarind-mcp`, then use its authorize action. If the server is listed under **MCPs → From plugins** without an authorize action, see the fallback below. |
| Codex CLI | Authorize the `tamarind` server through the client's own MCP login flow, then start a new task. |
| Claude Code | Run `/mcp`, select `tamarind`, and choose **Authenticate**. |
| Claude Desktop | **Settings → Connectors**, find Tamarind, and connect. |
| Claude.ai | **Settings → Connectors**, find Tamarind, and connect. |
| Other MCP clients | Use the client's own connector or MCP settings UI to authorize `https://mcp.tamarind.bio/mcp`. |

A browser window handles the authorization. Never ask the user to paste a client secret, access token, refresh token, authorization code, or API key into chat, and never read those values back to them.

After authorization completes, repeat the no-spend checks above. Start a new task first if the client only discovers tools at task creation.

## Fallback: connect with an API key

If the client offers no working authorize action, the server can be connected with an API key instead of OAuth. Send the user to <https://app.tamarind.bio/api-docs/mcp-server>, which carries the exact per-client steps and the key itself. Do not attempt the setup on the user's behalf, and do not accept the key in chat.

Prefer this only after the client's own authorize path has failed. It is a per-machine manual setup, not the intended flow.

## Diagnose failures

- Missing tools: install or enable the `tamarind-mcp` plugin, then start a new task if the client requires tool discovery at task creation.
- Unauthorized: authorize once through the client's UI above. Do not loop authorization attempts.
- Authorization opens but is rejected: report what the browser showed and stop. Do not retry with different values or suggest editing OAuth settings by hand.
- Tool not found: query the live catalog instead of assuming a remembered tool name.
- File upload egress blocked: use `uploadFile` inline for files up to its inline limit, or allow the exact host returned by `uploadFile` before retrying the streaming upload.
- Rate limit or service error: stop and report it. Never turn a connectivity failure into a compute submission.

After setup succeeds, route selection to `tamarind-mcp-tool-discovery` and a known single job to `tamarind-mcp-submit-and-poll`.

---
name: tamarind-mcp-setup
description: Connect, authenticate, or troubleshoot the Tamarind Bio MCP server and run a no-spend connectivity check. Use when Tamarind MCP tools are missing, OAuth is incomplete or rejected, or the user wants MCP rather than the Tamarind CLI. Not for selecting a scientific model or submitting compute.
---

# Connect Tamarind MCP

Use the remote MCP server configured by this plugin. Do not install the Tamarind CLI, request an API key, or recreate Tamarind HTTP calls.

## Check availability

Confirm that these server tools are callable:

1. Call `listModalities`.
2. Call `listTags`.
3. Call `getAvailableTools` with a narrow `search` such as `boltz`.
4. Call `getJobSchema` for one returned tool.

These calls do not create jobs or consume compute. Do not call `submitJob` or `submitBatch` as a setup test.

## Authenticate

If a tool reports unauthorized or the client shows that Tamarind is disconnected, use the MCP client's connection UI to reconnect `https://mcp.tamarind.bio/mcp` and complete OAuth. Never ask the user to paste a client secret, access token, refresh token, authorization code, or API key into chat.

After OAuth completes, repeat the no-spend checks. There is no separate MCP `auth status` tool; a successful account-scoped catalog call is the connectivity signal.

## Diagnose failures

- Missing tools: install or enable the `tamarind-mcp` plugin/server, then start a new task if the client requires tool discovery at task creation.
- Unauthorized: reconnect through the client and complete OAuth once; do not loop authentication attempts.
- Tool not found: query the live catalog instead of assuming a remembered tool name.
- File upload egress blocked: use `uploadFile` inline for files up to its inline limit, or allow the exact host returned by `uploadFile` before retrying the streaming upload.
- Rate limit or service error: stop and report it. Never turn a connectivity failure into a compute submission.

After setup succeeds, route selection to `tamarind-mcp-tool-discovery` and a known single job to `tamarind-mcp-submit-and-poll`.

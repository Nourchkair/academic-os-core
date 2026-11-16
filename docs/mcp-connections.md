# MCP tool connections

MCP connections are optional external tool servers. Academia OS guides the
student through four steps:

1. **Add server** — paste the remote MCP URL, or open **Local server** for a
   command-based server. A name is optional; Academia can derive one from the
   URL.
2. **Inspect tools** — Academia connects once and reads the server's actual
   declared tool list.
3. **Trust read-only tools** — a remote server must be explicitly trusted before
   any of its declared read-only tools can be granted.
4. **Enable** — only the selected read-only tools are enabled. Nothing runs
   automatically.

## Security model

- Server-declared `readOnlyHint` is a trust boundary, not a sandbox.
- A remote server starts untrusted.
- Persistent grants are read-only only. Action tools can be granted for one chat
  conversation in the dashboard, where they are marked as actions and run only
  through Academia's proxy.
- Remote OAuth tokens live in the macOS Keychain; connection records hold only
  authorization metadata.
- Local commands are advanced configuration and remain explicit.
- Disconnecting removes the local record and its tokens.

## Plain-language trust

When a remote server is inspected, the UI explains:

> This server says these tools only read data. Academia cannot verify that claim,
> so you must trust the server before granting access.

The student can cancel at any step. An MCP connection never starts enabled.

## Per-conversation chat grants

There is no separate connection picker in the chat sidebar. Mention the
connection in the message (`@Aside`) or name it in plain language. Academia
detects the connection and asks for permission before sending:

- **Deny** — send the message without that connection's tools.
- **Allow** — grant the connection for this conversation only.
- **Always allow** — persist the chat grant for this browser profile in local
  storage. Settings → Connections → MCP tools shows and revokes it.

The in-app agent calls granted tools through Academia's proxy (`mcp.call` for API
providers, `academia_mcp_call` for Codex). The external server is never loaded
directly into the model host. Each call validates the exact connection and tool
against the conversation grant; server-level persistent grants remain read-only.

Every call appends `mcp.tool_called` to Activity with the connection and tool
name, never credentials or full arguments. Action tools can affect signed-in
accounts. The assistant must not submit schoolwork, send messages, make
payments, or change account settings, and the student remains the final
authority for every action.

## Downloading a file into Academia

When the student asks for a file to be downloaded into Academia, the chat can
complete the handoff without giving the model a filesystem path:

1. `academia_download_intake` starts a one-time loopback upload endpoint and
   returns its URL, a random token, the staging folder, and the size/extension
   limits.
2. The granted browser downloads the file with its signed-in session and POSTs
   the bytes to that localhost URL. Academia writes the file into its private
   staging folder. Cookies and session tokens never leave the browser.
3. `academia_import_download` copies the staged file into the exact recognized
   semester or course `00_INBOX`, records HTTP provenance, starts supported
   extraction, removes the staged copy, and appends `file.imported` to Activity.

The intake tools exist only in a chat run that has an external MCP grant. They
reject arbitrary local paths, hidden names, unsupported extensions, empty or
oversized files, and unauthenticated uploads. They do not overwrite academic
material; duplicate content is reported instead of copied again.

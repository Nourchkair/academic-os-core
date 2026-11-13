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
- Write tools are never grantable.
- Remote OAuth tokens live in the macOS Keychain; connection records hold only
  authorization metadata.
- Local commands are advanced configuration and remain explicit.
- Disconnecting removes the local record and its tokens.

## Plain-language trust

When a remote server is inspected, the UI explains:

> This server says these tools only read data. Academia cannot verify that claim,
> so you must trust the server before granting access.

The student can cancel at any step. An MCP connection never starts enabled.

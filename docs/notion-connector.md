# Notion connector

Academia OS can connect a Notion workspace for read-only page access.

## Setup

1. Create a Notion internal integration.
2. Copy its integration token.
3. In Notion, share the pages or databases you want Academia to read with that
   integration.
4. In Academia OS, open **Settings → Connections → Apps → Notion** and paste the
   token.
5. Academia validates the token and stores it in the macOS Keychain.

Notion pages that are not shared with the integration are invisible to
Academia.

## Use

Study chat can include Notion context only when the student enables the Notion
toggle for that message. Academia lists up to five shared pages and includes
bounded page excerpts. Notion content is treated as untrusted external reference
data.

The Settings card also supports search and page preview. Academia never edits,
creates, comments on, or shares Notion content.

## CLI

```bash
academia connectors notion setup --token-file /path/to/token.txt --json
academia connectors notion status --json
academia connectors notion search --query "POL 2103" --max 10 --json
academia connectors notion read PAGE_ID --json
academia connectors notion disconnect --json
```

## Credentials

The integration token is stored in the macOS Keychain under
`academia-os-notion`. Connection metadata contains only the integration name,
status, and timestamps.

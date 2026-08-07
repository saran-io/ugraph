# ADR-0002: Share is an outbound boundary

## Status

Accepted (feat-share).

## Context

Users want `ugraph x` (and later Instagram / WhatsApp / MCP targets) to publish
what they just captured. Mixing that into bare `ugraph` or into the knowledge
pipeline would create silent, irreversible social side effects and a much
larger attack surface.

## Decision

Share is a separate product surface with a hard boundary:

| Layer | Allowed | Forbidden |
|---|---|---|
| Knowledge core (`ingest`, `person`, `extract`, `lint`, `verify`) | Read/write vault files | Network publish, social APIs |
| Share (`ugraph x`, later `ugraph share …`) | Outbound publish after preview | Mutating concepts/sources as a side effect of posting |
| Bare `ugraph` | Capture / person detection | Never posts |

Rules:

1. **Explicit command only.** Posting requires `ugraph x` (or a future
   `ugraph share <target>`). Bare `ugraph` never publishes.
2. **Confirm by default.** Interactive preview, then `[y/N]`. `--yes` is the
   only automation escape hatch. `--dry-run` never hits the network.
3. **Secrets outside the vault.** Credentials live under
   `~/.config/ugraph/share/` with mode `0600`. They are never written into the
   Obsidian KB, never logged, never printed by `status`.
4. **Least privilege.** X v1 stores only the four OAuth 1.0a user-context
   secrets needed to create a post. No app-only bearer for writes.
5. **Receipts, not secrets.** Each successful post appends a redacted receipt
   (destination, post id, URL, char count, timestamp). Receipts never contain
   tokens.
6. **One target per milestone.** This branch ships X only. Instagram,
   WhatsApp, iMessage, and generic MCP adapters are future targets behind the
   same `ShareDraft` contract — not new capture commands.
7. **No invented content.** Share posts exactly the user-supplied text (or
   clipboard). It does not auto-summarize the KB into a tweet.

## Consequences

- Share can fail closed without affecting ingest or person capture.
- Adding MCP destinations means mapping a `ShareDraft` to one authenticated
  tool call; it does not change the KB schema.
- If a secret file is world-readable, the CLI refuses to use it until
  permissions are fixed.

## Kill criteria

Remove or freeze the share surface if:

- credentials cannot be kept out of the vault, or
- posting cannot stay behind an explicit confirm, or
- a destination requires unofficial / TOS-breaking automation as the only path.

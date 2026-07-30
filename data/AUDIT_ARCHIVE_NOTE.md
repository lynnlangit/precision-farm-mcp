# data/audit.jsonl.pre-a1-fix

This is the audit log as it stood before Phase A / A1 fixed
`AuditLog`'s hash-chain race (the host process and a spawned MCP server
subprocess both held long-lived instances pointed at the same file; a
cached `prev_hash` went stale the moment the other process appended,
forking the chain). Its entries predate the fix, so `AuditLog.verify()`
correctly reports `False` on this file -- that's expected, not a bug in
`verify()`.

Kept locally for reference; not tracked in git (see `.gitignore`) since it
contains real local usage, not synthetic fixture data. `data/audit.jsonl`
itself starts fresh from the fix onward and is expected to verify cleanly.

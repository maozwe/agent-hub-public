# Project instructions

- Codex manages version numbers for every user-visible update. Follow `VERSIONING.md`; keep `version.json`, Android version metadata and `CHANGELOG.md` consistent. Rebuilding the same update does not require another bump.
- The existing `maozwe/agent-hub` repository must remain private. Use a separate clean source snapshot in `maozwe/agent-hub-public` for public code; never copy private Git history, machine-specific reports, credentials, configuration or task data.
- Do not create release tags or publish Releases/installers until the user explicitly asks. The requested future public Release must contain both EXE and APK with concise release notes.
- Preserve manually assigned execution ownership. Additional participants are coordination metadata and do not gain worker/MCP permissions.
- For local Hub task execution, follow `AGENT-HUB-PROMPT.he.md` and check the actual MCP connection and identity. Do not claim tasks or start monitoring merely because this repository is open.

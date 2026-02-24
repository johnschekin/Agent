# Platform Conventions

- Working directory is the Agent repo root.
- Use CLI tools in `scripts/` for all discovery/testing/persistence.
- Strategy files live in `workspaces/<family>/strategies/`.
- Evidence files live in `workspaces/<family>/evidence/`.
- Update `workspaces/<family>/checkpoint.json` after each iteration loop.

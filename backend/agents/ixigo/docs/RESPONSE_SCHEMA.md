# Ixigo agent response

Ixigo follows the **standard travel agent response schema** when `fetch_offers=True`.

See **[backend/docs/AGENT_RESPONSE_SCHEMA.md](../../docs/AGENT_RESPONSE_SCHEMA.md)** for the full definition (response shape, `filtered` = Phase 2 + `offers`, app usage). All agents (Ixigo, Cleartrip, etc.) return the same structure so the app can consume one format.

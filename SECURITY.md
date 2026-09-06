# Security policy

## Project status

XRF Agent Provenance is experimental research software. It must not be used as a standalone authorization, malware-detection, or sandbox boundary. A detected watermark does not prove benign or malicious intent, and failure to detect one does not establish safety.

## Reporting a vulnerability

Please do not include exploit details, secrets, personal data, or live production identifiers in a public issue. Until a dedicated security contact is published, open a GitHub issue containing only a minimal, non-sensitive description and request a private reporting channel from the maintainer.

Useful reports include tag forgery without the secret, false-positive frames in ordinary text, parser inconsistencies, denial-of-service inputs, cross-tenant tag confusion, secret exposure, and cases where protected code or security-sensitive text is unexpectedly modified.

## Operational guidance

- Use a randomly generated watermark key of at least 32 bytes.
- Keep watermark keys separate from model-provider API keys.
- Rotate keys and identify them with a non-secret key ID.
- Never embed raw user, tenant, or session identifiers.
- Treat detection as provenance telemetry and combine it with authorization, sandboxing, audit logs, and content inspection.
- Apply input-size and scan-time limits before using the detector at a gateway.

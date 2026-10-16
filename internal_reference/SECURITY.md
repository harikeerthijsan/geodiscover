# Security

## Release controls

- No `.env` file or live provider credential is included.
- Provider calls are disabled when credentials are absent.
- Per-run call caps and optional spend caps are enforced by the discovery engine.
- Demo records are blocked from strict customer release.
- Customer release requires non-demo data, complete mandatory fields and independent QA.

## Immediate team action

The uploaded development archive contained a committed `.env`. That file was excluded from v4. Rotate any Google, AWS or other credential that was present in the archive and remove it from repository history where practical.

## Production requirements

- secrets manager and key rotation
- SSO/MFA and project-scoped RBAC
- TLS and secure cookies/token handling
- managed database backups and encryption
- evidence object storage with access logs
- vulnerability/dependency scanning
- monitoring, alerting and audit retention
- penetration/security review
- source-specific data retention, attribution and deletion controls

Do not expose the local demo environment directly to the internet.

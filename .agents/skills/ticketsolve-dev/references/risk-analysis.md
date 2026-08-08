# TicketSolve Risk Analysis Reference

Reference document for risk factors, security controls, and mitigation strategies.
Original master file: `RISK_ANALYSIS_AND_MITIGATION_PLAN.md`

## Summary of Key Risks & Action Items

| Risk Item | Level | Current Baseline | Target Mitigation |
|---|---|---|---|
| **1. Backup Location** | High | Saved locally at `/var/backups/ticketsolve` on VPS | AWS S3 Encrypted Backup with S3 Object Lock |
| **2. Admin Authentication** | High | Argon2 hash + Login throttling (5 tries / 15m) | Multi-Factor Authentication (TOTP / WebAuthn) for System Admins |
| **3. Content Security Policy** | Medium | `Content-Security-Policy-Report-Only` mode | Transition to Enforcing CSP (`Content-Security-Policy`) via Self-hosting assets & script nonces |
| **4. Database Concurrency** | Medium | SQLite3 + WAL + Online Backup API | PostgreSQL + TLS + Connection Pooling (PgBouncer) |
| **5. File Attachment Security** | Medium | Signature allowlist & Extension verification | ClamAV Anti-Virus stream scanning & file quarantine |
| **6. Audit Log Retention** | Low-Med | Stored inside SQLite `SecurityAuditLog` table | Structured JSON logs shipped to AWS CloudWatch / SIEM (Append-only) |

## Related Documentation

- `RISK_ANALYSIS_AND_MITIGATION_PLAN.md` — Complete risk analysis roadmap
- `SECURITY_AND_SYSTEM_ARCHITECTURE_REPORT.md` — Core architecture & security baseline
- `references/architecture.md` — System architecture details

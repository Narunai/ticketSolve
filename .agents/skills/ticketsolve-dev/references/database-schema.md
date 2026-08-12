# TicketSolve Database Schema Reference

All models are in `tickets/models.py` (1746 lines, 30+ models).

## Database Engine Configuration (Dual-Engine)

The project supports both PostgreSQL 16+ (Production High-Concurrency) and SQLite3 (Local Development) via environment variables in `ticket_system/settings.py`:

- `DB_ENGINE`: `postgresql` or `sqlite` (Default: `postgresql` in production, `sqlite` in development)
- `DB_NAME`: Database name (e.g. `ticketsolve_db`)
- `DB_USER`: Database user (e.g. `ticketsolve_user`)
- `DB_PASSWORD`: Database password
- `DB_HOST`: Host address (e.g. `localhost` or RDS Endpoint)
- `DB_PORT`: Database port (e.g. `5432`)
- `DB_SSLMODE`: SSL mode (e.g. `prefer` or `require`)
- `DB_CONN_MAX_AGE`: Connection Pooling age in seconds (Default: 600)

Backup functionality (`tickets/backup_service.py`) automatically adapts between PostgreSQL JSON dump (`call_command('dumpdata')`) and SQLite Online Backup API.

### Company (Line 11)

Hierarchical multi-tenant company structure.

| Field | Type | Notes |
|-------|------|-------|
| `name` | CharField(255) | unique |
| `parent` | FK → self | nullable, `related_name='subsidiaries'` |
| `created_at` | DateTimeField | auto |

Key methods:
- `get_all_subsidiary_ids()` — recursive list of all descendant IDs
- `get_all_subsidiaries()` — recursive list of Company objects
- `get_parents()` — list from immediate parent to root
- `get_full_path()` — e.g. "Parent Corp > Branch A > Unit 1"

---

### CustomUser (Line 83)

Extends `AbstractUser` with role and company assignment.

| Field | Type | Notes |
|-------|------|-------|
| `role` | CharField(20) | `SYSTEM_ADMIN`, `SYSTEM_SUB_ADMIN`, `CLIENT_ADMIN`, `CLIENT_STAFF`, `CLIENT_USER` |
| `company` | FK → Company | nullable |
| `simple_password_enabled` | BooleanField | Allows shorter passwords |
| `simple_password_approved_by` | FK → self | Who approved simple password |

---

### Ticket (Line 385)

Core ticket entity.

| Field | Type | Notes |
|-------|------|-------|
| `title` | CharField(255) | |
| `description` | TextField | blank allowed |
| `status` | CharField(20) | `OPEN`, `IN_PROGRESS`, `DEPLOYMENT_REQUESTED`, `READY_TO_DEPLOY`, `RESOLVED`, `CLOSED` |
| `priority` | CharField(10) | `LOW`, `MEDIUM`, `HIGH` |
| `category` | CharField(50) | Legacy: `HARDWARE`, `SOFTWARE`, `NETWORK`, `ACCOUNT`, `OTHER` |
| `ticket_category` | FK → TicketCategory | nullable, company-specific categories |
| `module_category` | FK → ModuleCategory | nullable |
| `resolution_category` | FK → ResolutionCategory | nullable |
| `resolution_notes` | TextField | blank |
| `custom_fields_data` | JSONField | Company-defined custom fields |
| `attachment` | FileField | Legacy single attachment |
| `company` | FK → Company | |
| `created_by` | FK → CustomUser | |
| `assigned_to` | FK → CustomUser | nullable |
| `created_at` | DateTimeField | auto |
| `updated_at` | DateTimeField | auto |
| `status_changed_at` | DateTimeField | indexed, for automation |

---

### TicketAttachment (Line 862)

Multi-file attachments (new system, replaces legacy `attachment` field).

| Field | Type | Notes |
|-------|------|-------|
| `ticket` | FK → Ticket | `related_name='attachments'` |
| `file` | FileField | `upload_to='ticket_attachments/'` |
| `uploaded_at` | DateTimeField | auto |

---

### TicketComment (Line 798)

Comments/replies on tickets.

| Field | Type | Notes |
|-------|------|-------|
| `ticket` | FK → Ticket | `related_name='comments'` |
| `user` | FK → CustomUser | |
| `text` | TextField | |
| `created_at` | DateTimeField | auto |

---

### CommentAttachment (Line 880)

File attachments on comments.

| Field | Type | Notes |
|-------|------|-------|
| `comment` | FK → TicketComment | `related_name='attachments'` |
| `file` | FileField | `upload_to='comment_attachments/'` |
| `uploaded_at` | DateTimeField | auto |

---

## Category Models

### TicketCategory (Line 141)

Company-specific ticket categories (replaces legacy `category` choices).

| Field | Type | Notes |
|-------|------|-------|
| `name` | CharField(100) | |
| `company` | FK → Company | nullable (null = global) |
| `description` | TextField | blank |
| `icon_code` | CharField(50) | default='folder' |
| `color_code` | CharField(20) | default='#6366f1' |
| `is_active` | BooleanField | |

### ResolutionCategory (Line 166)

Categories for how a ticket was resolved.

### ModuleCategory (Line 187)

Software module/component categories.

---

## Configuration Models

### CompanyTicketConfig (Line 234)

Per-company ticket form configuration.

| Field | Type | Notes |
|-------|------|-------|
| `company` | OneToOne → Company | `related_name='ticket_config'` |
| `ticket_prefix` | CharField(10) | e.g. "ACME-" |
| `require_resolution_note` | BooleanField | |
| `custom_help_text` | TextField | Shown at top of ticket form |
| `allow_file_attachments` | BooleanField | |

### CompanyTicketField (Line 249)

Dynamic custom fields per company.

| Field | Type | Notes |
|-------|------|-------|
| `company` | FK → Company | |
| `field_key` | CharField(50) | unique per company |
| `label` | CharField(150) | |
| `field_type` | CharField(20) | `TEXT`, `TEXTAREA`, `NUMBER`, `SELECT`, `DATE`, `BOOLEAN` |
| `options` | JSONField | For SELECT dropdowns |
| `is_required`, `is_visible`, `is_custom` | BooleanField | |
| `order` | IntegerField | Sort order |

### TicketStatusConfig (Line 212)

Customizable status names and badge colors per company.

### TicketAutomationConfig (Line 312)

Auto-escalation rules (e.g. OPEN > 24h → IN_PROGRESS).

---

## Email & Notification Models

### SMTPConfiguration (Line 1044)

Outbound email server configuration.

| Field | Type | Notes |
|-------|------|-------|
| `company` | FK → Company | |
| `host`, `port`, `username` | Standard SMTP fields | |
| `password` | **EncryptedCharField** | Fernet encryption |
| `use_tls`, `use_ssl` | BooleanField | |
| `filter_issue_only`, `issue_keywords` | Boolean + Text | Required subject-keyword filter; bounded CSV |
| `ignore_keyword_filter_enabled`, `ignore_keywords` | Boolean + Text | Higher-priority subject ignore filter; bounded CSV |
| `is_active` | BooleanField | Only one active per company |

### NotificationConfig (Line 1532)

Controls which roles receive email notifications per event type per company.

### EmailLog (Line 664)

Audit log of all sent emails.

### InAppNotification (Line 819)

Private notifications shown in the navbar bell icon.

---

## Inbound Email Models

### InboundEmailReceipt (Line 1233)

Emails received from IMAP polling.

### InboundEmailRoutingRule (Line 1350)

Rules for auto-routing inbound emails to companies/categories.

### EmailToTicketSchedule (Line 1404)

IMAP polling schedule configuration.

### EmailToTicketRunLog (Line 1468)

Execution log for each polling run.

---

## Audit & Security Models

### TicketAuditLog (Line 714)

Tracks all ticket field changes (old value → new value).

### SecurityAuditLog (Line 763)

Login attempts, password changes, security events.

### AuthenticationThrottle (Line 752)

IP-based brute-force protection.

---

## Backup & Report Models

### BackupLog (Line 506)

Records of database backups.

### BackupSchedule (Line 541)

Scheduled automatic backup configuration.

### MonthlyReportSchedule (Line 923)

Auto-generated monthly PDF report schedules.

### ReportViewLog (Line 899)

Tracks who viewed/downloaded reports.

---

## Chatbot Microservice Database Schema (`chatbot.db`)

SQLite database managed by `chatbot_service/database.py`.

### `system_config`
- `is_active` (INTEGER): Master chatbot toggle (1 = ON, 0 = OFF)
- `api_key_enc` (TEXT): Encrypted Gemini API key (Fernet)
- `model_name` (TEXT): allowlisted Gemini model identifier (recommended `gemini-3.6-flash`)
- `system_prompt` (TEXT): Master system instruction prompt

### `custom_knowledge`
- `id` (INTEGER PK)
- `title` (TEXT): Guide/Manual title
- `content` (TEXT): Markdown or plain text knowledge content
- `is_active` (INTEGER): Active toggle
- `updated_at` (TIMESTAMP)

Chatbot authentication does not have a separate password table. Nginx verifies
the existing Django session and System Admin/Sub Admin role before proxying admin
requests.

### `chat_history`
- `session_id` (TEXT)
- `user_id` (TEXT)
- `role` (TEXT)
- `message` (TEXT)
- `created_at` (TIMESTAMP)

### `admin_audit_log`
- `actor_id` (TEXT): Django user primary key supplied by the trusted auth subrequest
- `action` (TEXT): config/knowledge administrative action
- `target_id` (TEXT): knowledge entry ID when applicable
- `details` (TEXT): bounded metadata only; never API key or prompt/knowledge content
- `created_at` (TIMESTAMP)

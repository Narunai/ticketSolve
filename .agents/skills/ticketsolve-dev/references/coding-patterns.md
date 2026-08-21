# TicketSolve Coding Patterns Reference

## 1. Template Tags in JavaScript (CRITICAL RULE)

### ❌ NEVER DO THIS

```html
<script>
    {% if object %}
    openModal({{ object.pk }}, '{{ object.title }}');
    {% endif %}
</script>
```

### ✅ ALWAYS DO THIS

Pass values through `data-*` attributes on HTML elements:

```html
<!-- In HTML (template tags OK here) -->
<form id="my-form"
      data-is-edit="{% if object %}true{% else %}false{% endif %}"
      data-item-pk="{% if object %}{{ object.pk }}{% else %}0{% endif %}"
      data-dashboard-url="{% url 'dashboard' %}">
```

```html
<script>
    // In JS — pure JavaScript, no template tags
    const form = document.getElementById('my-form');
    if (form.dataset.isEdit === "true") {
        const pk = parseInt(form.dataset.itemPk, 10);
        openModal(pk);
    }
</script>
```

### Why?

- IDE JavaScript parsers cannot understand Django/Jinja2 template syntax
- Causes 50+ false-positive errors that obscure real bugs
- Server-rendered output is identical — `data-*` values are resolved before browser receives HTML

### Same Rule for Jinja2 (Chatbot Templates)

For `chatbot_service/templates/*.html` (Jinja2):

```html
<!-- ❌ BAD -->
<button onclick='editItem({{ entry.id }}, {{ entry.title | tojson }})'>Edit</button>

<!-- ✅ GOOD -->
<button class="btn-edit" data-id="{{ entry.id }}" data-title="{{ entry.title }}">Edit</button>

<script>
    document.querySelectorAll('.btn-edit').forEach(btn => {
        btn.addEventListener('click', function() {
            editItem(parseInt(this.dataset.id, 10), this.dataset.title);
        });
    });
</script>
```

---

## 2. Translation / i18n System

All English UI strings are centralized in `tickets/context_processors.py`:

```python
# context_processors.py
def language_processor(request):
    translations = {
        'lang': 'en',
        'dashboard': 'Dashboard',
        'tickets': 'Tickets',
        'cancel': 'Cancel',
        'save_changes': '💾 Save Changes',
        # ... 150+ keys
    }
    return {'t': SimpleNamespace(**translations)}
```

Usage in templates:
```html
<h1>{{ t.dashboard }}</h1>
<button>{{ t.save_changes }}</button>
```

**Rules**:
- All user-facing text must use `{{ t.key_name }}` — never hardcode English in templates
- Add new keys to `context_processors.language_processor` dictionary
- Variable names use `snake_case`

---

## 3. Role-Based Permissions

### 5 Roles (hierarchy)

| Role | Code | Scope |
|------|------|-------|
| System Administrator | `SYSTEM_ADMIN` | Full system access, all companies |
| System Sub-Administrator | `SYSTEM_SUB_ADMIN` | Most admin features, all companies |
| Client Administrator | `CLIENT_ADMIN` | Admin for own company + subsidiaries |
| Client Staff | `CLIENT_STAFF` | View/edit tickets in own company |
| Client User | `CLIENT_USER` | Create tickets, view own tickets only |

### Permission Check Patterns

```python
# In views.py — mixin-based
class MyView(SystemAdminRequiredMixin, TemplateView):
    # Only SYSTEM_ADMIN and SYSTEM_SUB_ADMIN can access
    pass

# In templates — conditional rendering
{% if user.role == 'SYSTEM_ADMIN' or user.role == 'SYSTEM_SUB_ADMIN' %}
    <a href="{% url 'user_list' %}">Manage Users</a>
{% endif %}
```

### Company Hierarchy Access

- `SYSTEM_ADMIN` / `SYSTEM_SUB_ADMIN`: See all companies' tickets
- `CLIENT_ADMIN`: See own company + all subsidiary companies' tickets
- `CLIENT_STAFF` / `CLIENT_USER`: See only own company's tickets

---

## 4. Form Submission Pattern

Ticket forms use **AJAX XHR** (not standard form POST) for progress tracking:

```javascript
// Pattern used in ticket_form.html
const formData = new FormData(form);
const xhr = new XMLHttpRequest();

xhr.upload.onprogress = function(event) {
    // Update progress bar
};

xhr.onload = function() {
    if (xhr.status >= 200 && xhr.status < 400) {
        // Success → redirect
        window.location.href = xhr.responseURL || form.dataset.dashboardUrl;
    } else if (xhr.status === 413) {
        // File too large
    } else {
        // Generic error
    }
};

xhr.open('POST', form.action || window.location.href, true);
xhr.send(formData);
```

### Email Preview Modal (Edit Mode)

When editing a ticket, before actual submission:
1. Check `form.dataset.isEdit === "true"`
2. Open email preview modal showing notification recipients
3. User confirms → set `form.dataset.modalConfirmed = "true"` → re-trigger submit
4. On second submit, the confirmed flag bypasses the modal

---

## 5. File Upload Pattern

Multi-file upload with client-side validation:

```javascript
const MAX_SIZE_BYTES = 10 * 1024 * 1024;  // 10MB per file
let accumulatedFiles = [];                  // Managed in-memory array

// On file input change → validate size → add to array
// On form submit → build DataTransfer → assign to real input
function updateRealInput() {
    const dt = new DataTransfer();
    accumulatedFiles.forEach(file => dt.items.add(file));
    fileInput.files = dt.files;
}
```

---

## 6. Django Template Inheritance

```
base.html
├── dashboard.html
├── ticket_form.html      (create/edit ticket)
├── ticket_detail.html    (view ticket + comments)
├── user_list.html
├── company_list.html
├── settings.html         (SMTP config)
├── report_dashboard.html (PDF reports)
├── email_timer.html      (inbound email config)
├── backup_list.html      (backup management)
└── ... (26 templates total)
```

### base.html provides:
- `{% block title %}` — Page title
- `{% block header_title %}` — H1 in content area
- `{% block content %}` — Main content
- Sidebar (auto-generated from role)
- Top navbar with notifications badge
- Chatbot widget (authenticated users only)

---

## 7. Static Assets

- Django: `tickets/static/` → collected to `/var/www/ticketSolve/staticfiles/`
- Chatbot: `chatbot_service/static/` → served directly by FastAPI
- CSS framework: **Tailwind CSS** (via CDN in `base.html`)
- Font: **Inter** (Google Fonts)

---

## 8. Email System

### Outbound (Notifications)
- Configured via `SMTPConfiguration` model (Django admin or Settings page)
- SMTP passwords encrypted with Fernet
- Triggered by `signals.py` on ticket create/update/comment
- `NotificationConfig` controls which roles receive emails per company

### Inbound (Email → Ticket)
- `email_to_ticket.py` polls IMAP mailboxes
- Matching rules in `InboundEmailRoutingRule`
- New/unapproved mailbox contacts queue for manual approval even when a system user or active routing rule matches; only a contact that remains in the mailbox directory and has a successful imported receipt with an administrator decision may auto-import
- Routing rules select the assignee/company after approval; they never grant permission to bypass the approval queue
- Scheduled via `ticketsolve-email-to-ticket.timer`

---

## 9. IDE Diagnostics & Problems Detection Standard (Mandatory Verification)

### Post-Modification Checklist:
1. **Detect Problems**: Always inspect the IDE Problems panel / diagnostic notifications (`@[current_problems]`).
2. **Target State**: The workspace must display **`No problem` (0 errors, 0 diagnostics)**.
3. **Scratch/Temporary Code Isolation**: When executing scratch scripts, clean them up or ensure proper module imports (`sys.path.append(...)`) so the IDE linter never reports import errors.
4. **Zero Unchecked Errors**: Never finish a task or prompt the user while any diagnostic error remains unresolved in the Problems panel.

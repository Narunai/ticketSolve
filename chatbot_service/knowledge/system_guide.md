# TicketSolve User Guide

TicketSolve is a multi-tenant IT support ticket system. Users can create tickets,
track their own requests, add comments and download authorized attachments.
Company staff can manage tickets only within the company scope granted to their
account. System administrators manage cross-company configuration.

## Ticket workflow

1. Open **New Ticket**, enter a clear subject and description, select priority
   and category, then attach only the files needed to explain the issue.
2. Follow progress from the Dashboard. Common states are Open, In Progress,
   Resolved and Closed. Some organizations also use deployment approval states.
3. Add a comment to provide more information. Do not put passwords, API keys or
   other secrets in a ticket or attachment.
4. Contact an administrator when a ticket or company is not visible. The
   assistant cannot grant access or change a ticket.

## Email to Ticket

Authorized mailboxes can import messages into a review queue. Depending on the
approved sender and routing rules, a message may be imported automatically or
wait for an administrator to approve or reject it. Duplicate Message-ID values
are not imported twice.

## Notifications and reports

Notification recipients are calculated from the configured rules. A ticket
editor can preview recipients and make a one-time recipient adjustment for that
single update. Monthly PDF reports are limited to the organization scope of the
requesting administrator.

## Security guidance

- Sign in only through the official TicketSolve HTTPS domain.
- Never share a password, one-time code, SMTP credential or API key in chat.
- The AI assistant provides guidance only. It cannot access private ticket data,
  modify accounts, send email, approve requests or perform server operations.
- Report suspicious access, unexpected email or repeated login failures to a
  system administrator.

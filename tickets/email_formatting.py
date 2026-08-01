from django.template.loader import render_to_string


def build_formal_email(
    *,
    heading,
    greeting,
    introduction,
    details=None,
    paragraphs=None,
    action_label=None,
    action_url=None,
    closing='TicketSolve Service Desk',
    notice='This is an automated service notification. Please do not disclose ticket information to unauthorized persons.',
):
    """Return matching plain-text and HTML versions of a formal system email."""
    details = list(details or [])
    paragraphs = list(paragraphs or [])

    text_lines = [greeting, '', introduction]
    if details:
        text_lines.extend(['', 'Details'])
        text_lines.extend(f'{label}: {value}' for label, value in details)
    for paragraph in paragraphs:
        text_lines.extend(['', paragraph])
    if action_url:
        text_lines.extend(['', action_label or 'Open TicketSolve', action_url])
    text_lines.extend(['', 'Regards,', closing, '', notice])
    text_body = '\n'.join(str(line) for line in text_lines)

    html_body = render_to_string('tickets/email/formal_message.html', {
        'heading': heading,
        'greeting': greeting,
        'introduction': introduction,
        'details': details,
        'paragraphs': paragraphs,
        'action_label': action_label,
        'action_url': action_url,
        'closing': closing,
        'notice': notice,
    })
    return text_body, html_body

import re
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

@register.filter(name='render_ticket_description')
def render_ticket_description(value):
    """
    Renders raw description text into rich HTML:
    - Formats bracketed images [http.../file.png], file names, and SharePoint/OneDrive links <http...>
    - Converts raw URLs (http:// or https://) into styled clickable link badges.
    - Displays image URLs inline or as thumbnails.
    - Handles basic Markdown formatting (**bold**, *italic*, `code`, line breaks).
    """
    if not value:
        return ""

    # 1. Escape HTML input to prevent XSS
    escaped_text = escape(str(value))

    # 2. Pattern for combined pattern: [img_url]filename<link_url>
    # Example: [https://.../xlsx.png]ค่าใช้จ่าย.xlsx<https://sharepoint.../file.xlsx>
    combined_pattern = re.compile(
        r'\[(https?://[^\s\]]+)\]\s*([^<\n\[\]]+\.[a-zA-Z0-9]+)\s*&lt;(https?://[^\s&]+)&gt;'
    )

    def replace_combined(match):
        img_url = match.group(1)
        filename = match.group(2).strip()
        link_url = match.group(3)
        ext = filename.split('.')[-1].lower() if '.' in filename else ''
        
        icon = '📄'
        if ext in ['xlsx', 'xls', 'csv']:
            icon = '📊'
        elif ext in ['docx', 'doc']:
            icon = '📝'
        elif ext in ['pdf']:
            icon = '📕'
        elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
            icon = '🖼️'
        elif ext in ['zip', 'rar', '7z']:
            icon = '📦'

        return f'''<div class="my-2 p-3 rounded-xl bg-slate-950/60 border border-indigo-500/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-md">
            <div class="flex items-center gap-2.5 min-w-0">
                <img src="{img_url}" alt="{filename}" class="w-6 h-6 object-contain shrink-0" onerror="this.style.display='none'">
                <span class="text-sm font-semibold text-white truncate">{icon} {filename}</span>
            </div>
            <a href="{link_url}" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold text-indigo-300 bg-indigo-500/10 border border-indigo-500/30 hover:bg-indigo-500/20 hover:text-white transition-all shrink-0">
                <span>Open File / Sharepoint</span>
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
            </a>
        </div>'''

    html_out = combined_pattern.sub(replace_combined, escaped_text)

    # 3. Markdown images ![alt](url)
    md_img_pattern = re.compile(r'!\[([^\]]*)\]\((https?://[^\s\)]+)\)')
    def replace_md_img(match):
        alt = match.group(1) or 'Image'
        url = match.group(2)
        return f'<div class="my-2"><img src="{url}" alt="{alt}" class="max-h-64 rounded-xl border border-slate-700/80 shadow-md"></div>'

    html_out = md_img_pattern.sub(replace_md_img, html_out)

    # 4. Bracketed URLs &lt;https://...&gt; -> replace bracket with icon prefix before linkification
    bracket_url_pattern = re.compile(r'&lt;(https?://[^\s&]+)&gt;')
    html_out = bracket_url_pattern.sub(r'🔗 \1', html_out)

    # 5. Markdown links [text](url)
    md_link_pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)')
    def replace_md_link(match):
        label = match.group(1)
        url = match.group(2)
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-indigo-400 hover:text-indigo-300 font-semibold underline underline-offset-2 break-all">{label} 🔗</a>'

    html_out = md_link_pattern.sub(replace_md_link, html_out)

    # 6. Raw URLs (not already inside href or src attribute)
    raw_url_pattern = re.compile(r'(?<!href=")(?<!src=")(https?://[^\s<>"\'\]]+)')
    def replace_raw_url(match):
        url = match.group(1)
        if re.search(r'\.(png|jpg|jpeg|gif|webp)(\?.*)?$', url, re.IGNORECASE):
            return f'<div class="my-2"><img src="{url}" class="max-h-56 rounded-xl border border-slate-700 shadow-md"></div>'
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer" class="text-indigo-400 hover:text-indigo-300 font-medium underline underline-offset-2 break-all">{url}</a>'

    html_out = raw_url_pattern.sub(replace_raw_url, html_out)

    # 7. Basic Markdown formatting (**bold**, *italic*, `code`)
    html_out = re.sub(r'\*\*(.*?)\*\*', r'<strong class="font-bold text-white">\1</strong>', html_out)
    html_out = re.sub(r'\*(.*?)\*', r'<em class="italic text-slate-300">\1</em>', html_out)
    html_out = re.sub(r'`([^`]+)`', r'<code class="bg-slate-800 text-indigo-300 font-mono text-xs px-1.5 py-0.5 rounded border border-slate-700">\1</code>', html_out)

    # 8. Convert newlines to <br>
    html_out = html_out.replace('\n', '<br>')

    return mark_safe(html_out)

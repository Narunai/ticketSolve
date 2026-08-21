/**
 * TicketSolve Live Real-Time Stream Controller
 * Server-Sent Events (SSE) Client for Real-time Bell Notifications, Theme-Adaptive Toasts & Dynamic Table Updates
 */

(function () {
    'use strict';

    if (!window.EventSource) {
        console.warn('[TicketSolve Live] EventSource not supported by browser.');
        return;
    }

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    // Audio chime using Web Audio API (gentle, unobtrusive 2-tone notification)
    function playNotificationSound() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (!AudioContext) return;
            const ctx = new AudioContext();
            if (ctx.state === 'suspended') {
                ctx.resume();
            }
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.connect(gain);
            gain.connect(ctx.destination);

            const now = ctx.currentTime;
            osc.frequency.setValueAtTime(587.33, now); // D5
            osc.frequency.setValueAtTime(880.00, now + 0.1); // A5
            gain.gain.setValueAtTime(0.04, now);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);

            osc.start(now);
            osc.stop(now + 0.35);
        } catch (e) {
            // Audio context blocked by autoplay policy until user interaction
        }
    }

    // Deduplication cache for toast notifications
    const recentToasts = new Set();

    // Floating Theme-Adaptive Toast Notification Component
    function showLiveToast(title, message, url, priority, notifKey) {
        const dedupeKey = notifKey || (title + '::' + message);
        if (recentToasts.has(dedupeKey)) return;
        recentToasts.add(dedupeKey);
        setTimeout(() => recentToasts.delete(dedupeKey), 4000);

        let container = document.getElementById('liveToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'liveToastContainer';
            container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none p-2';
            document.body.appendChild(container);
        }

        const isHigh = priority === 'HIGH' || priority === 'EMERGENCY';
        const isMedium = priority === 'MEDIUM';

        // Clean Modern SVG Icon and Color Indicators
        let iconHtml = '';
        let accentBorder = 'var(--theme-accent, #6366f1)';
        let accentGlow = 'var(--theme-accent-glow, rgba(99, 102, 241, 0.25))';

        if (isHigh) {
            accentBorder = '#f43f5e';
            accentGlow = 'rgba(244, 63, 94, 0.3)';
            iconHtml = `
                <div class="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 bg-rose-500/15 text-rose-500 border border-rose-500/30 shadow-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                </div>
            `;
        } else if (isMedium) {
            accentBorder = '#f59e0b';
            accentGlow = 'rgba(245, 158, 11, 0.3)';
            iconHtml = `
                <div class="w-8 h-8 rounded-xl flex items-center justify-center shrink-0 bg-amber-500/15 text-amber-500 border border-amber-500/30 shadow-sm">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                </div>
            `;
        } else {
            iconHtml = `
                <div class="w-8 h-8 rounded-xl flex items-center justify-center shrink-0" style="background: var(--theme-accent-bg, rgba(99,102,241,0.15)); color: var(--theme-accent, #6366f1); border: 1px solid var(--theme-accent-border, rgba(99,102,241,0.3));">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>
                </div>
            `;
        }

        const toast = document.createElement('div');
        toast.className = 'pointer-events-auto relative rounded-2xl p-3.5 shadow-2xl transition-all duration-300 transform translate-y-2 opacity-0 flex items-start gap-3 border cursor-pointer backdrop-blur-xl overflow-hidden glass-panel';
        toast.style.cssText = `
            background: var(--glass-panel-bg, rgba(15, 23, 42, 0.9));
            border: 1px solid var(--glass-panel-border, rgba(255, 255, 255, 0.1));
            color: var(--text-main, #f8fafc);
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.25), 0 0 15px ${accentGlow};
        `;

        toast.innerHTML = `
            <div class="absolute left-0 top-0 bottom-0 w-1" style="background: ${accentBorder};"></div>
            ${iconHtml}
            <div class="min-w-0 flex-1 pl-0.5">
                <div class="flex items-center justify-between gap-2">
                    <h5 class="text-xs font-bold truncate" style="color: var(--text-main, inherit);">${escapeHtml(title)}</h5>
                    <span class="text-[9px] uppercase tracking-wider font-bold" style="color: var(--theme-accent, #6366f1);">Just Now</span>
                </div>
                <p class="text-xs mt-0.5 line-clamp-2 leading-relaxed" style="color: var(--text-muted, #94a3b8);">${escapeHtml(message)}</p>
            </div>
            <button type="button" class="shrink-0 p-1 text-slate-400 hover:text-slate-200 transition-colors leading-none text-base" onclick="event.stopPropagation(); this.closest('.pointer-events-auto').remove();">&times;</button>
        `;

        if (url) {
            toast.addEventListener('click', function () {
                window.location.href = url;
            });
        }

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => {
            toast.classList.remove('translate-y-2', 'opacity-0');
            toast.classList.add('translate-y-0', 'opacity-100');
        });

        playNotificationSound();

        // Auto dismiss after 7 seconds
        setTimeout(() => {
            toast.classList.add('opacity-0', 'translate-x-4');
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 300);
        }, 7000);
    }

    // Bell Badge Real-time Updater
    function updateBellBadge(unreadCount) {
        const bellBtn = document.getElementById('bellNotificationButton') || document.querySelector('button[onclick*="toggleNotificationMenu"]');
        if (!bellBtn) return;

        let badge = document.getElementById('bellNotificationBadge') || bellBtn.querySelector('.notif-badge, span.absolute');
        if (unreadCount && unreadCount > 0) {
            if (!badge) {
                badge = document.createElement('span');
                badge.id = 'bellNotificationBadge';
                badge.className = 'notif-badge absolute -right-1.5 -top-1.5 min-w-4 rounded-full bg-theme-gradient px-1 text-center text-[9px] font-bold leading-4 text-white shadow-sm';
                bellBtn.appendChild(badge);
            }
            badge.textContent = unreadCount;
            badge.classList.remove('hidden');
            badge.style.display = '';

            // Micro-animation for bell icon
            bellBtn.classList.add('scale-110');
            setTimeout(() => bellBtn.classList.remove('scale-110'), 300);
        } else if (badge) {
            badge.classList.add('hidden');
            badge.textContent = '0';
        }
    }

    // Notification Dropdown Real-time Updater
    function prependNotificationItem(data) {
        const dropdown = document.getElementById('notificationMenuDropdown');
        if (!dropdown) return;

        // Update unread subtitle
        const unreadSub = document.getElementById('notificationUnreadSubtitle') || dropdown.querySelector('.text-\\[10px\\].text-slate-400, .text-\\[10px\\].text-slate-500');
        if (unreadSub && typeof data.unread_count !== 'undefined') {
            unreadSub.textContent = `${data.unread_count} unread`;
        }

        // Update Mark all read button
        const markAllContainer = document.getElementById('notificationMarkAllContainer');
        if (markAllContainer && data.unread_count > 0 && !markAllContainer.querySelector('form')) {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
            markAllContainer.innerHTML = `
                <form method="post" action="/notifications/read-all/">
                    <input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">
                    <button type="submit" class="text-[10px] font-semibold text-theme-accent hover:underline cursor-pointer">Mark all read</button>
                </form>
            `;
        }

        // Prepend to list
        const listContainer = document.getElementById('notificationListContainer') || dropdown.querySelector('.max-h-80');
        if (listContainer) {
            // Remove empty state if present
            const emptyNotice = document.getElementById('notificationEmptyState') || listContainer.querySelector('.text-center');
            if (emptyNotice) emptyNotice.remove();

            const item = document.createElement('a');
            item.href = data.open_url || (data.ticket_id ? `/ticket/${data.ticket_id}/` : '/notifications/');
            item.className = 'block px-4 py-3 hover:opacity-90 transition-all bg-theme-bg';
            item.style.borderBottom = '1px solid var(--glass-panel-border, rgba(255,255,255,0.06))';
            item.innerHTML = `
                <div class="flex items-start gap-2">
                    <span class="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full shadow-sm animate-pulse" style="background: var(--theme-accent, #6366f1);"></span>
                    <div class="min-w-0">
                        <div class="truncate text-xs font-semibold" style="color: var(--text-main, #f8fafc);">${escapeHtml(data.title)}</div>
                        <div class="mt-0.5 line-clamp-2 text-[10px]" style="color: var(--text-muted, #94a3b8);">${escapeHtml(data.message)}</div>
                        <div class="mt-1 text-[9px]" style="color: var(--text-subtle, #64748b);">${data.created_at || 'Just now'}</div>
                    </div>
                </div>
            `;
            listContainer.insertBefore(item, listContainer.firstChild);
        }
    }

    // Dynamic In-App Notification Arrival Handler
    function handleLiveNotificationCreated(data) {
        updateBellBadge(data.unread_count);
        prependNotificationItem(data);
        showLiveToast(data.title, data.message, data.open_url, 'MEDIUM', 'notif-' + (data.id || data.title));
    }

    // Dynamic Live Table Insertion on Dashboard
    function handleLiveTicketCreated(ticket) {
        // Prevent duplicate insertion if already rendered
        if (document.getElementById(`ticket-row-${ticket.id}`)) return;

        // Show Toast Notification
        showLiveToast(
            `New Ticket #${ticket.id}`,
            `${ticket.title} (${ticket.company_name || 'General'})`,
            ticket.url,
            ticket.priority,
            `ticket-created-${ticket.id}`
        );

        // Check if on Dashboard table
        const tbody = document.getElementById('ticketTableBody');
        if (!tbody) return;

        // Remove empty state placeholder if present
        const emptyRow = tbody.querySelector('td[colspan="9"]');
        if (emptyRow) {
            emptyRow.closest('tr').remove();
        }

        // Build priority badge HTML
        let priorityBadge = '';
        if (ticket.priority === 'HIGH' || ticket.priority === 'EMERGENCY') {
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/15 text-rose-500 border border-rose-500/25"><span class="w-1.5 h-1.5 rounded-full bg-rose-500"></span>${escapeHtml(ticket.priority_display || 'High')}</span>`;
        } else if (ticket.priority === 'MEDIUM') {
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-500 border border-amber-500/25"><span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span>${escapeHtml(ticket.priority_display || 'Medium')}</span>`;
        } else {
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/15 text-sky-500 border border-sky-500/25"><span class="w-1.5 h-1.5 rounded-full bg-sky-500"></span>${escapeHtml(ticket.priority_display || 'Low')}</span>`;
        }

        // Build status badge HTML (New ticket is always Open)
        const statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/15 text-blue-500 border border-blue-500/25"><span class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></span>${escapeHtml(ticket.status_display || 'Open')}</span>`;

        // Module category tag
        let moduleHtml = '';
        if (ticket.module_category) {
            moduleHtml = `<span class="block text-[10px] font-medium text-emerald-500">🧩 ${escapeHtml(ticket.module_category)}</span>`;
        }

        // Assigned To cell formatting
        let assignedHtml = `<span class="italic text-[11px]" style="color: var(--text-subtle, #94a3b8);">Not Assigned</span>`;
        if (ticket.assigned_to && ticket.assigned_to !== 'Not Assigned' && ticket.assigned_to !== 'None') {
            assignedHtml = `<span class="font-medium" style="color: var(--text-main, inherit);">${escapeHtml(ticket.assigned_to)}</span>`;
        }

        // Create new table row element (Exact 9 Columns matching Dashboard table structure)
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-slate-800/10 transition-colors bg-emerald-500/15';
        tr.id = `ticket-row-${ticket.id}`;
        tr.innerHTML = `
            <!-- 1. ID -->
            <td class="px-4 py-2 font-mono text-[11px] font-bold whitespace-nowrap" style="color: var(--theme-accent, #6366f1);">#${ticket.id}</td>

            <!-- 2. Title -->
            <td class="px-4 py-2 max-w-[260px]">
                <a href="${ticket.url}" class="font-medium hover:text-theme-accent transition-colors truncate block flex items-center gap-1.5" style="color: var(--text-main, inherit);">
                    ${escapeHtml(ticket.title)}
                    <span class="inline-block px-1.5 py-0.2 rounded text-[9px] bg-emerald-500/20 text-emerald-500 font-bold tracking-wider shrink-0">NEW</span>
                </a>
            </td>

            <!-- 3. Category + Module Category -->
            <td class="px-4 py-2">
                <span style="color: var(--text-muted, inherit);">${escapeHtml(ticket.category || 'General')}</span>
                ${moduleHtml}
            </td>

            <!-- 4. Priority -->
            <td class="px-4 py-2 whitespace-nowrap">${priorityBadge}</td>

            <!-- 5. Status -->
            <td class="px-4 py-2 whitespace-nowrap">${statusBadge}</td>

            <!-- 6. Created By -->
            <td class="px-4 py-2 whitespace-nowrap font-medium" style="color: var(--text-muted, inherit);">${escapeHtml(ticket.created_by || 'System')}</td>

            <!-- 7. Assigned To -->
            <td class="px-4 py-2 whitespace-nowrap">${assignedHtml}</td>

            <!-- 8. Created At -->
            <td class="px-4 py-2 text-[10px] tabular-nums whitespace-nowrap" style="color: var(--text-subtle, #94a3b8);">${ticket.created_at || 'Just now'}</td>

            <!-- 9. Actions -->
            <td class="px-4 py-2 text-center whitespace-nowrap">
                <a href="${ticket.edit_url || ticket.url}" class="inline-flex items-center px-2 py-1 rounded text-[10px] font-semibold border hover:border-theme-border transition-all" style="color: var(--text-main, inherit); background: var(--glass-card-bg, rgba(30,41,59,0.5)); border-color: var(--glass-panel-border, rgba(255,255,255,0.1));">Edit Ticket</a>
            </td>
        `;

        // Prepend to top of table
        tbody.insertBefore(tr, tbody.firstChild);

        // Smoothly fade out green highlight after 3 seconds
        setTimeout(() => {
            tr.classList.remove('bg-emerald-500/15');
        }, 3000);
    }

    // Dynamic Live Status Updates
    function handleLiveStatusUpdated(data) {
        showLiveToast(
            `Ticket #${data.id} Status Updated`,
            `"${data.title}" changed to ${data.new_status_display}`,
            data.url,
            'MEDIUM',
            `status-updated-${data.id}-${data.new_status}`
        );

        const row = document.getElementById(`ticket-row-${data.id}`);
        if (row) {
            row.classList.add('bg-indigo-500/15');
            setTimeout(() => {
                row.classList.remove('bg-indigo-500/15');
            }, 3000);
        }
    }

    // Dynamic Live Comment Updates
    function handleLiveCommentCreated(data) {
        showLiveToast(
            `New Reply on Ticket #${data.ticket_id}`,
            `${data.author}: ${data.content}`,
            `/ticket/${data.ticket_id}/`,
            'LOW',
            `comment-${data.ticket_id}-${Date.now()}`
        );
    }

    // SSE Connection Initializer with Auto-Reconnect & Background Tab Optimization
    let activeEventSource = null;
    let backgroundTimeout = null;

    function connectStream() {
        if (activeEventSource) {
            try { activeEventSource.close(); } catch(e) {}
            activeEventSource = null;
        }

        const streamUrl = '/events/stream/';

        try {
            activeEventSource = new EventSource(streamUrl);

            activeEventSource.addEventListener('ticket_created', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveTicketCreated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse ticket_created event:', err);
                }
            });

            activeEventSource.addEventListener('ticket_status_updated', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveStatusUpdated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse ticket_status_updated event:', err);
                }
            });

            activeEventSource.addEventListener('comment_created', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveCommentCreated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse comment_created event:', err);
                }
            });

            activeEventSource.addEventListener('notification_created', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveNotificationCreated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse notification_created event:', err);
                }
            });

            activeEventSource.onerror = function () {
                console.debug('[SSE] Stream cycling / reconnecting...');
            };
        } catch (err) {
            console.warn('[SSE] Could not establish EventSource connection:', err);
        }
    }

    function disconnectStream() {
        if (activeEventSource) {
            try { activeEventSource.close(); } catch(e) {}
            activeEventSource = null;
        }
    }

    // Tab visibility handling: pause stream if tab is inactive for > 2 mins to save bandwidth/threads, resume instantly on focus
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            backgroundTimeout = setTimeout(function() {
                disconnectStream();
            }, 120000); // 2 minutes background grace period
        } else {
            if (backgroundTimeout) {
                clearTimeout(backgroundTimeout);
                backgroundTimeout = null;
            }
            if (!activeEventSource) {
                connectStream();
            }
        }
    });

    function initEventStream() {
        connectStream();
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initEventStream);
    } else {
        initEventStream();
    }
})();

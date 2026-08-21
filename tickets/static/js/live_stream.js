/**
 * TicketSolve Live Real-Time Stream Controller
 * Server-Sent Events (SSE) Client for Push Toasts & Dynamic Table Updates (No Refresh)
 */

(function () {
    'use strict';

    if (!window.EventSource) {
        console.warn('[TicketSolve Live] EventSource not supported by browser.');
        return;
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

    // Floating Toast Notification Component
    function showLiveToast(title, message, url, priority) {
        let container = document.getElementById('liveToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'liveToastContainer';
            container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none p-2';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = 'pointer-events-auto rounded-xl p-3.5 shadow-2xl transition-all duration-300 transform translate-y-2 opacity-0 flex items-start gap-3 border cursor-pointer';
        
        let borderClass = 'border-slate-700/80 bg-slate-900/95 text-slate-100';
        let iconHtml = '🎫';
        if (priority === 'HIGH' || priority === 'EMERGENCY') {
            borderClass = 'border-rose-500/50 bg-slate-900/95 text-rose-300 ring-1 ring-rose-500/30';
            iconHtml = '🚨';
        } else if (priority === 'MEDIUM') {
            borderClass = 'border-amber-500/50 bg-slate-900/95 text-amber-300 ring-1 ring-amber-500/30';
            iconHtml = '⚠️';
        } else {
            borderClass = 'border-indigo-500/50 bg-slate-900/95 text-slate-100 ring-1 ring-indigo-500/30';
            iconHtml = '🔔';
        }
        toast.className += ' ' + borderClass;

        toast.innerHTML = `
            <span class="text-xl shrink-0 leading-none">${iconHtml}</span>
            <div class="min-w-0 flex-1">
                <div class="flex items-center justify-between gap-2">
                    <h5 class="text-xs font-bold truncate text-white">${title}</h5>
                    <span class="text-[9px] uppercase tracking-wider text-theme-accent font-semibold">Just Now</span>
                </div>
                <p class="text-xs text-slate-300 mt-0.5 line-clamp-2 leading-relaxed">${message}</p>
            </div>
            <button type="button" class="text-slate-500 hover:text-slate-300 shrink-0 text-sm leading-none p-1" onclick="event.stopPropagation(); this.closest('div').remove();">&times;</button>
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

    // Dynamic Live Table Insertion on Dashboard
    function handleLiveTicketCreated(ticket) {
        // Show Toast Notification
        showLiveToast(
            `New Ticket #${ticket.id}`,
            `${ticket.title} (${ticket.company_name || 'General'})`,
            ticket.url,
            ticket.priority
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
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/20"><span class="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse"></span>${ticket.priority_display}</span>`;
        } else if (ticket.priority === 'MEDIUM') {
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/20"><span class="w-1.5 h-1.5 rounded-full bg-amber-400"></span>${ticket.priority_display}</span>`;
        } else {
            priorityBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-sky-500/15 text-sky-400 border border-sky-500/20"><span class="w-1.5 h-1.5 rounded-full bg-sky-400"></span>${ticket.priority_display}</span>`;
        }

        // Build status badge HTML (New ticket is always Open)
        const statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold bg-blue-500/15 text-blue-400 border border-blue-500/20"><span class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></span>${ticket.status_display || 'Open'}</span>`;

        // Create new table row element
        const tr = document.createElement('tr');
        tr.className = 'border-b border-slate-800/40 hover:bg-slate-800/30 transition-all bg-emerald-500/15';
        tr.id = `ticket-row-${ticket.id}`;
        tr.innerHTML = `
            <td class="px-4 py-2 font-mono text-[11px] font-bold text-slate-400 whitespace-nowrap">#${ticket.id}</td>
            <td class="px-4 py-2 font-semibold text-white max-w-xs truncate">
                <a href="${ticket.url}" class="hover:text-theme-accent transition-colors flex items-center gap-1.5">
                    ${ticket.title}
                    <span class="inline-block px-1.5 py-0.2 rounded text-[9px] bg-emerald-500/20 text-emerald-300 font-bold tracking-wider">NEW</span>
                </a>
            </td>
            <td class="px-4 py-2 text-slate-300 whitespace-nowrap">${ticket.company_name || '-'}</td>
            <td class="px-4 py-2 whitespace-nowrap">
                <span class="inline-flex items-center gap-1 text-[11px] text-slate-300">
                    <span class="w-1.5 h-1.5 rounded-full bg-theme-accent"></span>${ticket.category || 'General'}
                </span>
            </td>
            <td class="px-4 py-2 whitespace-nowrap">${priorityBadge}</td>
            <td class="px-4 py-2 whitespace-nowrap">${statusBadge}</td>
            <td class="px-4 py-2 text-slate-300 font-medium whitespace-nowrap">${ticket.created_by || 'User'}</td>
            <td class="px-4 py-2 whitespace-nowrap"><span class="text-slate-500 italic text-[11px]">${ticket.assigned_to || 'Not Assigned'}</span></td>
            <td class="px-4 py-2 text-[10px] text-slate-400 tabular-nums whitespace-nowrap">${ticket.created_at || 'Just now'}</td>
            <td class="px-4 py-2 text-center whitespace-nowrap">
                <a href="${ticket.edit_url || ticket.url}" class="inline-flex items-center px-2 py-1 rounded text-[10px] font-semibold text-slate-300 bg-slate-800 hover:bg-theme-bg hover:text-theme-accent border border-slate-700/60 transition-all">Edit</a>
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
            'MEDIUM'
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
            'LOW'
        );
    }

    // SSE Connection Initializer with Auto-Reconnect
    function initEventStream() {
        const streamUrl = '/events/stream/';
        let eventSource = null;

        try {
            eventSource = new EventSource(streamUrl);

            eventSource.addEventListener('ticket_created', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveTicketCreated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse ticket_created event:', err);
                }
            });

            eventSource.addEventListener('ticket_status_updated', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveStatusUpdated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse ticket_status_updated event:', err);
                }
            });

            eventSource.addEventListener('comment_created', function (e) {
                try {
                    const data = JSON.parse(e.data);
                    handleLiveCommentCreated(data);
                } catch (err) {
                    console.error('[SSE] Failed to parse comment_created event:', err);
                }
            });

            eventSource.onerror = function (e) {
                // EventSource automatically reconnects, log for debugging
                console.debug('[SSE] Stream disconnected or reconnection in progress...');
            };
        } catch (err) {
            console.warn('[SSE] Could not establish EventSource connection:', err);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initEventStream);
    } else {
        initEventStream();
    }
})();

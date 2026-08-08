(function () {
    const scriptElem = document.currentScript;
    const scriptSrc = scriptElem ? scriptElem.src : window.location.origin + '/static/widget.js';
    
    // Determine base paths based on script location
    let cssUrl, apiBaseUrl;
    if (scriptSrc.includes('/chatbot-static/')) {
        cssUrl = '/chatbot-static/widget.css?v=3';
        apiBaseUrl = '/api';
    } else {
        const origin = new URL(scriptSrc).origin;
        cssUrl = `${origin}/static/widget.css?v=3`;
        apiBaseUrl = `${origin}/api`;
    }

    // Inject CSS
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = cssUrl;
    document.head.appendChild(link);

    // Create Widget Container HTML
    const widgetHTML = `
        <div id="gemini-chatbot-root">
            <button id="gemini-chat-toggle" title="Ask AI Assistant">
                💬
            </button>
            <div id="gemini-chat-window" class="hidden">
                <div class="chat-header">
                    <div class="header-info">
                        <span class="avatar">🤖</span>
                        <div>
                            <strong>TicketSolve AI Assistant</strong>
                            <span class="status-indicator">● Online</span>
                        </div>
                    </div>
                    <div class="header-actions">
                        <button id="gemini-chat-expand" title="Expand / Restore Window">⛶</button>
                        <button id="gemini-chat-close" title="Close">✕</button>
                    </div>
                </div>
                <div class="chat-messages" id="gemini-chat-messages">
                    <div class="message bot">Hello! I am your TicketSolve AI Assistant. How can I help you with system guides or features today?</div>
                </div>
                <div class="chat-input-area">
                    <input type="text" id="gemini-chat-input" placeholder="Type your question here..." autocomplete="off">
                    <button id="gemini-chat-send">Send</button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', widgetHTML);

    const toggleBtn = document.getElementById('gemini-chat-toggle');
    const chatWindow = document.getElementById('gemini-chat-window');
    const closeBtn = document.getElementById('gemini-chat-close');
    const expandBtn = document.getElementById('gemini-chat-expand');
    const sendBtn = document.getElementById('gemini-chat-send');
    const inputField = document.getElementById('gemini-chat-input');
    const messagesContainer = document.getElementById('gemini-chat-messages');

    let isChatActive = true;
    let isExpanded = false;

    // Check system status from Microservice
    async function checkStatus() {
        try {
            const res = await fetch(`${apiBaseUrl}/status`);
            const data = await res.json();
            if (!data.is_active) {
                toggleBtn.style.display = 'none';
                chatWindow.classList.add('hidden');
                isChatActive = false;
            } else {
                toggleBtn.style.display = 'flex';
                isChatActive = true;
            }
        } catch (e) {
            console.warn('Chatbot service unreachable.');
        }
    }

    checkStatus();
    setInterval(checkStatus, 30000); // Poll status every 30s

    toggleBtn.addEventListener('click', () => {
        chatWindow.classList.toggle('hidden');
    });

    closeBtn.addEventListener('click', () => {
        chatWindow.classList.add('hidden');
    });

    expandBtn.addEventListener('click', () => {
        isExpanded = !isExpanded;
        if (isExpanded) {
            chatWindow.classList.add('expanded');
            expandBtn.innerHTML = '🗗';
            expandBtn.title = 'Restore Normal Window';
        } else {
            chatWindow.classList.remove('expanded');
            expandBtn.innerHTML = '⛶';
            expandBtn.title = 'Expand Window';
        }
    });

    function formatMarkdown(text) {
        if (!text) return '';
        // Escape HTML
        let escaped = text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // Simple Markdown parsing: **bold**
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        return escaped;
    }

    async function sendMessage() {
        const text = inputField.value.trim();
        if (!text || !isChatActive) return;

        // User message
        appendMessage(text, 'user');
        inputField.value = '';

        // Bot thinking placeholder
        const botLoadingId = appendMessage('Searching answer from Gemini AI...', 'bot loading');

        try {
            const res = await fetch(`${apiBaseUrl}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await res.json();
            
            const botMsgElem = document.getElementById(botLoadingId);
            if (data.status === 'success') {
                botMsgElem.innerHTML = formatMarkdown(data.response);
                botMsgElem.classList.remove('loading');
            } else {
                botMsgElem.innerHTML = formatMarkdown(data.response || 'An error occurred during processing.');
                botMsgElem.classList.remove('loading');
                botMsgElem.classList.add('error');
            }
        } catch (err) {
            const botMsgElem = document.getElementById(botLoadingId);
            if (botMsgElem) {
                botMsgElem.innerText = 'Error connecting to chatbot server.';
                botMsgElem.classList.remove('loading');
                botMsgElem.classList.add('error');
            }
        }

        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    sendBtn.addEventListener('click', sendMessage);
    inputField.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    function appendMessage(text, type) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${type}`;
        msgDiv.innerText = text;
        const msgId = 'msg-' + Date.now();
        msgDiv.id = msgId;
        messagesContainer.appendChild(msgDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return msgId;
    }
})();

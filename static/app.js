/* ══════════════════════════════════════════════════
   Chat con tu Excel — Frontend App
   ══════════════════════════════════════════════════ */

(function () {
    'use strict';

    // ── State ──
    const state = {
        token: null,
        username: null,
        role: null,
        sessionId: null,
        filename: null,
        sheets: [],
        selectedSheet: null,
        isRegistering: false,
    };

    // ── DOM refs ──
    const $ = (sel) => document.querySelector(sel);
    const loginView = $('#login-view');
    const chatView = $('#chat-view');
    const loginForm = $('#login-form');
    const loginAlert = $('#login-alert');
    const loginUsername = $('#login-username');
    const loginPassword = $('#login-password');
    const loginBtn = $('#login-btn');
    const toggleRegister = $('#toggle-register');
    const loginToggleText = $('#login-toggle-text');

    const chatMessages = $('#chat-messages');
    const welcomeMsg = $('#welcome-msg');
    const chatInput = $('#chat-input');
    const btnSend = $('#btn-send');
    const btnUploadToggle = $('#btn-upload-toggle');
    const uploadZone = $('#upload-zone');
    const fileInput = $('#file-input');
    const sheetSelector = $('#sheet-selector');
    const sheetSelect = $('#sheet-select');
    const sessionBadge = $('#session-badge');
    const headerUsername = $('#header-username');
    const headerRole = $('#header-role');
    const btnLogout = $('#btn-logout');
    const typingIndicator = $('#typing-indicator');
    const helpGuide = $('#help-guide');
    const helpToggle = $('#help-toggle');
    const helpContent = $('#help-content');

    // ═══════════════════════════════════════
    //  API Helpers
    // ═══════════════════════════════════════

    const API_BASE = '';

    async function apiCall(url, options = {}) {
        const headers = options.headers || {};
        if (state.token) {
            headers['Authorization'] = `Bearer ${state.token}`;
        }
        const response = await fetch(API_BASE + url, { ...options, headers });
        return response;
    }

    async function apiJSON(url, body, method = 'POST') {
        return apiCall(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
    }

    // ═══════════════════════════════════════
    //  Auth
    // ═══════════════════════════════════════

    function showAlert(msg, type = 'error') {
        loginAlert.textContent = msg;
        loginAlert.className = `alert alert-${type}`;
        loginAlert.style.display = 'block';
        setTimeout(() => { loginAlert.style.display = 'none'; }, 4000);
    }

    toggleRegister.addEventListener('click', () => {
        state.isRegistering = !state.isRegistering;
        if (state.isRegistering) {
            loginBtn.textContent = 'Registrarse';
            loginToggleText.innerHTML = '¿Ya tenés cuenta? <a id="toggle-register">Iniciá sesión</a>';
        } else {
            loginBtn.textContent = 'Iniciar sesión';
            loginToggleText.innerHTML = '¿No tenés cuenta? <a id="toggle-register">Registrate</a>';
        }
        // Re-attach event since we replaced innerHTML
        $('#toggle-register').addEventListener('click', arguments.callee);
    });

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginBtn.disabled = true;

        const username = loginUsername.value.trim();
        const password = loginPassword.value.trim();

        if (!username || !password) {
            showAlert('Completá usuario y contraseña');
            loginBtn.disabled = false;
            return;
        }

        try {
            let res;
            if (state.isRegistering) {
                res = await apiJSON('/auth/register', { username, password });
            } else {
                // OAuth2 form format for login
                const formData = new URLSearchParams();
                formData.append('username', username);
                formData.append('password', password);
                res = await apiCall('/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: formData,
                });
            }

            const data = await res.json();

            if (!res.ok) {
                showAlert(data.detail || 'Error de autenticación');
                loginBtn.disabled = false;
                return;
            }

            // Success
            state.token = data.access_token;
            state.username = data.username;
            state.role = data.role;
            enterChat();
        } catch (err) {
            showAlert('Error de conexión con el servidor');
            loginBtn.disabled = false;
        }
    });

    function enterChat() {
        loginView.style.display = 'none';
        chatView.classList.add('active');
        headerUsername.textContent = state.username;
        headerRole.textContent = state.role;
        loginBtn.disabled = false;
        addBotMessage(`Hola **${state.username}**! Subí un archivo Excel con el botón 📎 para empezar.`);
    }

    btnLogout.addEventListener('click', () => {
        state.token = null;
        state.username = null;
        state.role = null;
        state.sessionId = null;
        state.filename = null;
        state.sheets = [];
        chatView.classList.remove('active');
        loginView.style.display = 'flex';
        chatMessages.innerHTML = '';
        welcomeMsg && chatMessages.appendChild(welcomeMsg);
        chatInput.disabled = true;
        btnSend.disabled = true;
        updateSessionBadge();
        sheetSelector.classList.remove('active');
        uploadZone.classList.remove('active');
        loginUsername.value = '';
        loginPassword.value = '';
    });

    // ═══════════════════════════════════════
    //  File Upload
    // ═══════════════════════════════════════

    btnUploadToggle.addEventListener('click', () => {
        uploadZone.classList.toggle('active');
    });

    uploadZone.addEventListener('click', () => fileInput.click());

    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) uploadFile(file);
    });

    fileInput.addEventListener('change', () => {
        const file = fileInput.files[0];
        if (file) uploadFile(file);
        fileInput.value = '';
    });

    async function uploadFile(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['xlsx', 'xls'].includes(ext)) {
            addBotMessage('Solo se aceptan archivos **.xlsx** o **.xls**.');
            return;
        }

        addBotMessage(`Subiendo **${file.name}**...`);
        uploadZone.classList.remove('active');

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await apiCall('/upload', { method: 'POST', body: formData });
            const data = await res.json();

            if (!res.ok) {
                addBotMessage(`Error al subir: ${data.detail}`);
                return;
            }

            state.sessionId = data.session_id;
            state.filename = data.filename;
            state.sheets = data.sheets;
            state.selectedSheet = data.sheets[0]?.name || null;

            // Populate sheet selector
            sheetSelect.innerHTML = '';
            data.sheets.forEach((s) => {
                const opt = document.createElement('option');
                opt.value = s.name;
                opt.textContent = `${s.name} (${s.rows} filas, ${s.columns} cols)`;
                sheetSelect.appendChild(opt);
            });
            sheetSelector.classList.add('active');

            // Enable input
            chatInput.disabled = false;
            btnSend.disabled = false;
            chatInput.placeholder = 'Escribí tu pregunta sobre el Excel...';
            updateSessionBadge();

            // Show help guide with real columns
            const firstSheet = data.sheets[0];
            if (firstSheet) {
                buildHelpChips(firstSheet.column_names, firstSheet.column_types);
            }
            helpGuide.classList.add('active');

            // Summary message
            const sheetList = data.sheets
                .map((s) => `- **${s.name}**: ${s.rows} filas, ${s.columns} columnas\n  Columnas: ${s.column_names.join(', ')}`)
                .join('\n');
            addBotMessage(`Archivo **${data.filename}** cargado con éxito.\n\nSheets disponibles:\n${sheetList}\n\nYa podés hacerme preguntas.`);

        } catch (err) {
            addBotMessage('Error de conexión al subir el archivo.');
        }
    }

    sheetSelect.addEventListener('change', () => {
        state.selectedSheet = sheetSelect.value;
    });

    function updateSessionBadge() {
        if (state.filename) {
            sessionBadge.textContent = `📄 ${state.filename}`;
            sessionBadge.classList.remove('no-file');
        } else {
            sessionBadge.textContent = 'Sin archivo';
            sessionBadge.classList.add('no-file');
        }
    }

    // ═══════════════════════════════════════
    //  Help Guide
    // ═══════════════════════════════════════

    helpToggle.addEventListener('click', () => {
        helpToggle.classList.toggle('open');
        helpContent.classList.toggle('open');
    });

    function buildHelpChips(columns, types) {
        // Find a text column (for grouping/barras) and a numeric column (for aggregates)
        let textCol = null;
        let numCol = null;
        for (let i = 0; i < columns.length; i++) {
            if (!textCol && types[i] === 'text') textCol = columns[i];
            if (!numCol && types[i] === 'numeric') numCol = columns[i];
        }
        // Fallbacks
        textCol = textCol || columns[0] || 'columna1';
        numCol = numCol || columns[1] || columns[0] || 'columna2';

        const categories = [
            {
                icon: '📊', label: 'Datos', chips: [
                    { text: 'Contar filas', q: 'Cuantas filas tiene el dataset?' },
                    { text: 'Ver columnas', q: 'Que columnas tiene el dataset?' },
                    { text: 'Estadísticas', q: 'Dame las estadisticas descriptivas' },
                    { text: 'Valores únicos', q: `Que valores unicos hay en la columna ${textCol}?` },
                ]
            },
            {
                icon: '🔍', label: 'Consultas', chips: [
                    { text: 'Filtrar datos', q: `Cuantas filas tienen ${textCol} distinto de nulo?` },
                    { text: 'Promedio', q: `Cual es el promedio de ${numCol}?` },
                    { text: 'Agrupar', q: `Promedio de ${numCol} agrupado por ${textCol}` },
                    { text: 'Top N', q: `Top 3 filas con mayor valor en ${numCol}` },
                    { text: 'Correlación', q: `Correlacion entre las columnas numericas` },
                ]
            },
            {
                icon: '📈', label: 'Gráficos', chips: [
                    { text: 'Barras', q: `Grafico de barras de la columna ${textCol}` },
                    { text: 'Histograma', q: `Histograma de ${numCol}` },
                    { text: 'Torta', q: `Grafico de torta de la columna ${textCol}` },
                    { text: 'Box plot', q: `Box plot de ${numCol}` },
                    { text: 'Heatmap', q: 'Heatmap de correlacion' },
                ]
            },
        ];

        helpContent.innerHTML = categories.map(cat => `
            <div class="help-category">
                <span class="help-label">${cat.icon} ${cat.label}</span>
                <div class="help-chips">
                    ${cat.chips.map(c => `<button class="chip" data-q="${c.q}">${c.text}</button>`).join('')}
                </div>
            </div>
        `).join('');

        // Attach click listeners to new chips
        helpContent.querySelectorAll('.chip').forEach((chip) => {
            chip.addEventListener('click', () => {
                const question = chip.getAttribute('data-q');
                if (question && state.sessionId) {
                    chatInput.value = question;
                    sendMessage();
                }
            });
        });
    }

    // ═══════════════════════════════════════
    //  Chat
    // ═══════════════════════════════════════

    btnSend.addEventListener('click', sendMessage);
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Auto-resize textarea
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
    });

    async function sendMessage() {
        const question = chatInput.value.trim();
        if (!question || !state.sessionId) return;

        // Add user message
        addUserMessage(question);
        chatInput.value = '';
        chatInput.style.height = 'auto';
        btnSend.disabled = true;
        showTyping(true);

        try {
            const res = await apiJSON('/query', {
                session_id: state.sessionId,
                question: question,
                sheet_name: state.selectedSheet,
            });

            showTyping(false);

            const data = await res.json();

            if (!res.ok) {
                addBotMessage(`Error: ${data.detail || 'No se pudo procesar la consulta.'}`);
                btnSend.disabled = false;
                return;
            }

            addBotMessage(data.answer, {
                chart: data.chart_base64,
                code: data.code_generated,
                operation: data.operation_used,
                mode: data.mode,
            });

        } catch (err) {
            showTyping(false);
            addBotMessage('Error de conexión con el servidor.');
        }

        btnSend.disabled = false;
        chatInput.focus();
    }

    // ═══════════════════════════════════════
    //  Message Rendering
    // ═══════════════════════════════════════

    function addUserMessage(text) {
        if (welcomeMsg && welcomeMsg.parentNode) welcomeMsg.remove();

        const msg = document.createElement('div');
        msg.className = 'message message-user';
        msg.innerHTML = `
            <div class="message-bubble">${escapeHtml(text)}</div>
            <div class="message-meta">${timeNow()}</div>
        `;
        chatMessages.appendChild(msg);
        scrollToBottom();
    }

    function addBotMessage(text, extras = {}) {
        if (welcomeMsg && welcomeMsg.parentNode) welcomeMsg.remove();

        const msg = document.createElement('div');
        msg.className = 'message message-bot';

        let html = `<div class="message-bubble">${formatMarkdown(text)}</div>`;

        if (extras.chart) {
            html += `<div class="message-chart"><img src="data:image/png;base64,${extras.chart}" alt="Gráfico"></div>`;
        }

        if (extras.code) {
            html += `<div class="message-code">${escapeHtml(extras.code)}</div>`;
        }

        if (extras.operation) {
            html += `<span class="message-operation">${extras.operation}</span>`;
        }

        const modeBadge = extras.mode ? ` · ${extras.mode}` : '';
        html += `<div class="message-meta">${timeNow()}${modeBadge}</div>`;

        msg.innerHTML = html;
        chatMessages.appendChild(msg);
        scrollToBottom();
    }

    function showTyping(show) {
        if (show) {
            typingIndicator.classList.add('active');
            chatMessages.appendChild(typingIndicator);
            scrollToBottom();
        } else {
            typingIndicator.classList.remove('active');
        }
    }

    function scrollToBottom() {
        requestAnimationFrame(() => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        });
    }

    // ── Text helpers ──

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function formatMarkdown(text) {
        if (!text) return '';
        let html = escapeHtml(text);
        // Bold **text**
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        // Inline code `text`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        // Code blocks ```...```
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        // Newlines
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    function timeNow() {
        return new Date().toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
    }

})();

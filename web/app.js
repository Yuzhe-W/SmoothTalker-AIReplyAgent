const API_BASE_URL = 'http://127.0.0.1:8080';
const GENERATE_URL = `${API_BASE_URL}/v1/replies:generate`;
const SELECT_URL = `${API_BASE_URL}/v1/replies:select`;
const WEB_USER_ID = 'web-user';

function setStatus(message) {
  const node = document.getElementById('status');
  if (node) {
    node.textContent = message;
  }
}

async function writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'absolute';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error('Clipboard copy unavailable in this browser context.');
  }
}

async function confirmSelection(sessionId, threadId, optionIndex) {
  if (!sessionId || !threadId) {
    return;
  }

  const res = await fetch(SELECT_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      thread_id: threadId,
      option_index: optionIndex,
      user_id: WEB_USER_ID,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `Feedback sync failed (${res.status})`);
  }
}

async function copyOption(text, optionIndex, sessionId, threadId) {
  try {
    await writeClipboard(text);
  } catch (e) {
    setStatus('Clipboard copy unavailable in this browser context.');
    return;
  }

  try {
    await confirmSelection(sessionId, threadId, optionIndex);
    setStatus(`Copied option ${optionIndex + 1} and saved it to thread memory.`);
  } catch (_) {
    setStatus(`Copied option ${optionIndex + 1}, but feedback sync failed.`);
  }
}

function renderOptions(options, sessionId, threadId) {
  const out = document.getElementById('options');
  out.textContent = '';

  if (!options.length) {
    out.textContent = 'No options returned.';
    return;
  }

  options.forEach((option, index) => {
    const card = document.createElement('div');
    card.className = 'option';

    const head = document.createElement('div');
    head.className = 'option-head';

    const label = document.createElement('strong');
    label.textContent = `Option ${index + 1}`;

    const copyButton = document.createElement('button');
    copyButton.className = 'copy-small';
    copyButton.type = 'button';
    copyButton.textContent = 'Copy';
    copyButton.addEventListener('click', () => {
      copyOption(option, index, sessionId, threadId).catch(() => {
        setStatus(`Copied option ${index + 1}, but feedback sync failed.`);
      });
    });

    const text = document.createElement('div');
    text.textContent = option;

    head.appendChild(label);
    head.appendChild(copyButton);
    card.appendChild(head);
    card.appendChild(text);
    out.appendChild(card);
  });
}

async function generate() {
  const role = document.getElementById('role').value;
  const incoming = document.getElementById('incoming').value.trim();
  const threadId = `${role}-web`;
  const out = document.getElementById('options');

  if (!incoming) {
    out.textContent = '';
    setStatus('Paste an incoming message first.');
    return;
  }

  out.textContent = 'Generating...';
  setStatus('Generating...');

  try {
    const res = await fetch(GENERATE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, incoming_text: incoming, thread_id: threadId, user_id: WEB_USER_ID }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t || 'Request failed');
    }

    const data = await res.json();
    renderOptions(data.options || [], data.session_id || null, threadId);
    setStatus(`Received ${(data.options || []).length} option(s).`);
  } catch (e) {
    out.textContent = '';
    setStatus('Error: ' + (e && e.message ? e.message : 'unknown'));
  }
}

document.getElementById('go').addEventListener('click', generate);



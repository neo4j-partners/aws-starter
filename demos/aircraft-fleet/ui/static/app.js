import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { EvidenceGraph } from './graph.js';

const transcript = document.getElementById('transcript');
const welcome = document.getElementById('welcome');
const promptInput = document.getElementById('prompt');
const send = document.getElementById('send');
const starter = document.getElementById('starter');
const chatStatus = document.getElementById('chat-status');
const traceEntries = document.getElementById('trace-entries');
const traceEmpty = document.getElementById('trace-empty');
const clearSelection = document.getElementById('clear-selection');
const graph = new EvidenceGraph();
const calls = new Map();
let sessionId = crypto.randomUUID();
let controller;
let activeCall;

function appendMessage(role, text = '') {
  const message = document.createElement('article');
  message.className = `message ${role}`;
  const speaker = document.createElement('strong');
  speaker.className = 'speaker';
  speaker.textContent = role === 'user' ? 'You' : 'Fleet assistant';
  const body = document.createElement('div');
  body.className = 'message-body';
  body.textContent = text;
  message.append(speaker, body);
  transcript.append(message);
  transcript.scrollTop = transcript.scrollHeight;
  return body;
}

function setSelection(call) {
  activeCall?.card.setAttribute('aria-pressed', 'false');
  activeCall = call;
  activeCall?.card.setAttribute('aria-pressed', 'true');
  clearSelection.hidden = !activeCall;
  graph.select(activeCall?.graph);
}

function resetTrace() {
  calls.clear();
  traceEntries.replaceChildren();
  traceEmpty.hidden = false;
  setSelection(null);
}

function displayName(name) {
  return {
    graph_query: 'Query fleet graph',
    graph_query_tool: 'Query fleet graph',
    vector_search: 'Search maintenance manuals',
    vector_search_tool: 'Search maintenance manuals',
  }[name] ?? name;
}

function startCall(event) {
  const item = document.createElement('li');
  const card = document.createElement('div');
  card.className = 'trace-card';
  const title = document.createElement('strong');
  title.textContent = displayName(event.name);
  const status = document.createElement('span');
  status.className = 'trace-status';
  status.dataset.state = event.call_id ? 'working' : 'reported';
  status.textContent = event.call_id ? 'Running' : 'Called';
  const parent = calls.get(event.parent_id);
  if (parent) {
    const label = document.createElement('span');
    label.className = 'trace-status';
    label.textContent = parent.name;
    card.append(label);
  }
  card.append(title, status);
  item.append(card);
  traceEntries.append(item);
  traceEmpty.hidden = true;
  calls.set(event.call_id ?? item, { name: title.textContent, item, card, status });
}

function finishCall(event) {
  const call = calls.get(event.call_id);
  if (!call) return;
  const duration = event.duration_ms < 1000
    ? `${event.duration_ms} ms` : `${(event.duration_ms / 1000).toFixed(1)} s`;
  call.status.dataset.state = event.status;
  const outcome = event.status === 'success' ? 'Completed' : 'Failed';
  call.status.textContent = `${outcome} · ${duration}`;
  if (event.graph_unavailable) call.status.textContent += ' · Graph unavailable';
  if (event.graph?.nodes.length) {
    call.graph = event.graph;
    graph.add(call.graph);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'trace-card';
    button.setAttribute('aria-pressed', 'false');
    button.title = 'Highlight graph evidence from this call';
    button.append(...call.card.childNodes);
    button.addEventListener('click', () => setSelection(activeCall === call ? null : call));
    call.item.replaceChildren(button);
    call.card = button;
  }
}

async function* streamEvents(response) {
  let buffer = '';
  for await (const chunk of response.body.pipeThrough(new TextDecoderStream())) {
    buffer += chunk;
    let end;
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      if (frame.startsWith('data: ')) yield JSON.parse(frame.slice(6));
    }
  }
}

function updateComposer() {
  send.disabled = Boolean(controller || !promptInput.value.trim());
  starter.disabled = Boolean(controller);
}

async function sendQuestion(question) {
  if (!question || controller) return;
  const turn = new AbortController();
  controller = turn;
  resetTrace();
  welcome.hidden = true;
  promptInput.value = '';
  updateComposer();
  chatStatus.textContent = 'Waiting for the fleet assistant';
  appendMessage('user', question);
  const answer = appendMessage('assistant', 'Working…');
  let text = '';
  let complete = false;

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: question, session_id: sessionId }),
      signal: turn.signal,
    });
    if (!response.ok) throw new Error('The fleet UI could not send this question.');
    for await (const event of streamEvents(response)) {
      if (turn.signal.aborted) return;
      switch (event.type) {
        case 'chunk':
          text += event.data;
          answer.textContent = text;
          transcript.scrollTop = transcript.scrollHeight;
          break;
        case 'agent':
        case 'tool':
          startCall(event);
          break;
        case 'tool_complete':
          finishCall(event);
          break;
        case 'complete':
          complete = true;
          break;
        case 'error':
          throw new Error(event.error || 'The fleet assistant could not complete this question.');
      }
    }
    if (!complete) throw new Error('The fleet assistant disconnected before finishing.');
    answer.innerHTML = DOMPurify.sanitize(marked.parse(text || 'The assistant returned no text.'), {
      FORBID_TAGS: ['img', 'style'],
    });
    answer.classList.add('formatted');
    transcript.scrollTop = transcript.scrollHeight;
  } catch (error) {
    if (turn.signal.aborted) return;
    const message = error.message || 'Could not reach the fleet assistant.';
    if (text) appendMessage('assistant', message);
    else answer.textContent = message;
  } finally {
    if (controller === turn) {
      controller = undefined;
      for (const { status } of calls.values()) {
        if (status.dataset.state === 'working') {
          status.dataset.state = 'reported';
          status.textContent = 'Result unavailable';
        }
      }
      chatStatus.textContent = complete ? 'Response complete' : 'Response ended';
      updateComposer();
      promptInput.focus();
    }
  }
}

document.getElementById('chat-form').addEventListener('submit', event => {
  event.preventDefault();
  sendQuestion(promptInput.value.trim());
});
promptInput.addEventListener('input', updateComposer);
promptInput.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendQuestion(promptInput.value.trim());
  }
});
starter.addEventListener('click', () => sendQuestion(
  'Find aircraft with hydraulic system issues. Show up to five maintenance events with their event IDs, aircraft tail numbers, faults, and corrective actions. Include the event IDs in the graph query results.',
));
clearSelection.addEventListener('click', () => setSelection(null));
document.getElementById('new-chat').addEventListener('click', () => {
  controller?.abort();
  controller = undefined;
  sessionId = crypto.randomUUID();
  transcript.replaceChildren(welcome);
  welcome.hidden = false;
  promptInput.value = '';
  chatStatus.textContent = 'New conversation';
  graph.reset();
  resetTrace();
  updateComposer();
  promptInput.focus();
});

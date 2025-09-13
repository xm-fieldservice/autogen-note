import { state, saveRecentTeam, loadRecentTeams } from './state.js';

const $ = (s, p = document) => p.querySelector(s);

const RECENT_AGENTS_KEY = 'notes_recent_agents_v1';

export function initAgentPicker() {
  loadRecentAgents();
  renderRecentAgents();

  $('#btn-pick-agent').addEventListener('click', () => $('#agent-file').click());
  $('#agent-file').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.selectedAgent = { name: file.name, path: file.name };
    saveRecentAgent(file.name, file.name);
    renderRecentAgents();
    console.log('[agent] selected', state.selectedAgent);
  });
  $('#recent-agents').addEventListener('change', (e) => {
    const val = e.target.value; if (!val) return;
    const path = decodeURIComponent(val);
    const item = (loadRecentAgents() || []).find(x => x.path === path);
    if (item) state.selectedAgent = { name: item.name, path: item.path };
    console.log('[agent] selected recent', state.selectedAgent);
  });
}

export function loadRecentAgents() {
  try { return JSON.parse(localStorage.getItem(RECENT_AGENTS_KEY) || '[]'); }
  catch { return []; }
}
export function saveRecentAgent(path, name) {
  const list = loadRecentAgents();
  const exists = list.find(x => x.path === path);
  if (!exists) {
    list.unshift({ path, name, ts: Date.now() });
    const kept = list.slice(0, 10);
    localStorage.setItem(RECENT_AGENTS_KEY, JSON.stringify(kept));
  }
}

function renderRecentAgents() {
  const list = loadRecentAgents();
  const sel = document.getElementById('recent-agents');
  sel.innerHTML = '<option value="">最近使用…</option>' + list.map(rt => `<option value="${encodeURIComponent(rt.path)}">${rt.name}</option>`).join('');
}

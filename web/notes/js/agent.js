import { state, saveRecentTeam, loadRecentTeams } from './state.js';

const $ = (s, p = document) => p.querySelector(s);

const RECENT_AGENTS_KEY = 'notes_recent_agents_v1';

export function initAgentPicker() {
  loadRecentAgents();
  renderRecentAgents();

  $('#btn-pick-agent').addEventListener('click', () => $('#agent-file').click());
  $('#agent-file').addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const code = await file.text();
      const url = URL.createObjectURL(new Blob([code], { type: 'text/javascript' }));
      const mod = await import(/* @vite-ignore */ url);
      state.selectedAgent = { name: file.name, code, module: mod };
      saveRecentAgent({ name: file.name, code });
      renderRecentAgents();
      console.log('[agent] selected & loaded module', state.selectedAgent);
    } catch (err) {
      console.warn('[agent] 加载失败:', err);
    }
  });
  $('#recent-agents').addEventListener('change', async (e) => {
    const val = e.target.value; if (!val) return;
    const name = decodeURIComponent(val);
    const item = (loadRecentAgents() || []).find(x => x.name === name);
    if (item && item.code) {
      try {
        const url = URL.createObjectURL(new Blob([item.code], { type: 'text/javascript' }));
        const mod = await import(/* @vite-ignore */ url);
        state.selectedAgent = { name: item.name, code: item.code, module: mod };
        console.log('[agent] selected recent & loaded module', state.selectedAgent);
      } catch (err) {
        console.warn('[agent] 重新加载模块失败:', err);
        state.selectedAgent = { name: item.name };
      }
    } else if (item) {
      state.selectedAgent = { name: item.name };
    }
  });
}

export function loadRecentAgents() {
  try { return JSON.parse(localStorage.getItem(RECENT_AGENTS_KEY) || '[]'); }
  catch { return []; }
}
export function saveRecentAgent(item) {
  const list = loadRecentAgents();
  const exists = list.find(x => x.name === item.name);
  const entry = { name: item.name, code: item.code || '', ts: Date.now() };
  if (exists) {
    // 覆盖更新并前置
    const filtered = list.filter(x => x.name !== item.name);
    filtered.unshift(entry);
    localStorage.setItem(RECENT_AGENTS_KEY, JSON.stringify(filtered.slice(0, 10)));
  } else {
    list.unshift(entry);
    localStorage.setItem(RECENT_AGENTS_KEY, JSON.stringify(list.slice(0, 10)));
  }
}

function renderRecentAgents() {
  const list = loadRecentAgents();
  const sel = document.getElementById('recent-agents');
  sel.innerHTML = '<option value="">最近使用…</option>' + list.map(rt => `<option value="${encodeURIComponent(rt.name)}">${rt.name}</option>`).join('');
}

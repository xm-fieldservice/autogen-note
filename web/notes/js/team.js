import { state, saveRecentTeam, loadRecentTeams } from './state.js';

const $ = (s, p = document) => p.querySelector(s);

export function initTeamPicker() {
  loadRecentTeams();
  renderRecent();

  $('#btn-pick-team').addEventListener('click', () => $('#team-file').click());
  $('#team-file').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.selectedTeam = { name: file.name, path: file.name };
    saveRecentTeam(file.name, file.name);
    renderRecent();
    console.log('[team] selected', state.selectedTeam);
  });
  $('#recent-teams').addEventListener('change', (e) => {
    const val = e.target.value; if (!val) return;
    const path = decodeURIComponent(val);
    const item = state.recentTeams.find(x => x.path === path);
    if (item) state.selectedTeam = { name: item.name, path: item.path };
    console.log('[team] selected recent', state.selectedTeam);
  });
}

function renderRecent() {
  const sel = document.getElementById('recent-teams');
  sel.innerHTML = '<option value="">最近使用…</option>' + state.recentTeams.map(rt => `<option value="${encodeURIComponent(rt.path)}">${rt.name}</option>`).join('');
}

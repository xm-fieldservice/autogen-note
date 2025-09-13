// 全局状态与通用工具（ES Module）
export const state = {
  activeTab: 'current',
  activeMode: 'note', // note | search | qa
  autoMode: false,
  selectedTeam: null,
  recentTeams: [],
  selectedTags: new Set(),
  topics: {
    current: [], // {id, title, tags:[], favorited, archived:false}
    archived: []
  },
  sessions: [], // {id, topicId, content, createdAt, favorited}
};

export const uid = () => Math.random().toString(36).slice(2, 10);

const RECENT_TEAMS_KEY = 'notes_recent_teams_v1';
export function loadRecentTeams() {
  try { state.recentTeams = JSON.parse(localStorage.getItem(RECENT_TEAMS_KEY) || '[]'); }
  catch { state.recentTeams = []; }
}
export function saveRecentTeam(path, name) {
  const exists = state.recentTeams.find(x => x.path === path);
  if (!exists) {
    state.recentTeams.unshift({ path, name, ts: Date.now() });
    state.recentTeams = state.recentTeams.slice(0, 10);
    localStorage.setItem(RECENT_TEAMS_KEY, JSON.stringify(state.recentTeams));
  }
}

export function escapeHTML(s) {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

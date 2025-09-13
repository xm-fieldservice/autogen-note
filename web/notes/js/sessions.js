import { state, escapeHTML } from './state.js';

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

export function renderSessions() {
  const ul = $('#session-list');
  ul.innerHTML = state.sessions.map(s => `<li class="session-item" data-id="${s.id}">
    <div class="session-content">${escapeHTML(s.content.slice(0, 200))}</div>
    <div class="session-actions">
      <button class="icon-btn fav" data-act="fav" title="收藏">${s.favorited ? '★' : '☆'}</button>
      <button class="icon-btn copy" data-act="copy" title="复制">📋</button>
      <button class="icon-btn delete" data-act="del" title="删除">🗑️</button>
    </div>
  </li>`).join('');

  $$('#session-list .session-item').forEach(item => {
    const id = item.dataset.id;
    $('[data-act="fav"]', item).addEventListener('click', () => { const s = state.sessions.find(x => x.id === id); if (s) { s.favorited = !s.favorited; renderSessions(); }});
    $('[data-act="copy"]', item).addEventListener('click', () => { const s = state.sessions.find(x => x.id === id); if (s) navigator.clipboard.writeText(s.content); });
    $('[data-act="del"]', item).addEventListener('click', () => {
      const s = state.sessions.find(x => x.id === id); if (!s) return;
      if (!confirm('确认删除该会话块及其在输出区的对应内容？')) return;
      // 移除列表数据
      state.sessions = state.sessions.filter(x => x.id !== id);
      renderSessions();
      // 同步移除输出区中最后一个匹配内容的块（简单匹配）
      const feed = document.getElementById('output-feed');
      const items = Array.from(feed.querySelectorAll('.feed-item .content'));
      const idx = items.map(n => n.textContent || '').lastIndexOf(s.content);
      if (idx >= 0) {
        const container = feed.querySelectorAll('.feed-item')[idx];
        container?.remove();
      }
    });
    item.addEventListener('click', (e) => {
      if (e.target.closest('.session-actions')) return;
      const s = state.sessions.find(x => x.id === id); if (s) $('#output-md').value = s.content; // 定位到输出区
    });
  });
}

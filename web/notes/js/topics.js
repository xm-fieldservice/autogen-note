import { state, uid, escapeHTML } from './state.js';
import { renderSessions } from './sessions.js';

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

export function renderTopics() {
  const lists = {
    current: $('#topic-list-current'),
    archived: $('#topic-list-archived'),
  };

  Object.entries(lists).forEach(([key, ul]) => {
    const set = state.topics[key] || [];
    const selectedTags = Array.from(state.selectedTags);
    const filtered = selectedTags.length === 0 ? set : set.filter(t => selectedTags.every(tag => (t.tags || []).includes(tag)));
    ul.innerHTML = filtered.map(t => topicItemHTML(t)).join('');
  });

  $$('#topic-list-current .topic-item, #topic-list-archived .topic-item').forEach(item => bindTopicItem(item));
}

export function addTopicFromSelection() {
  const id = uid();
  const tags = Array.from(state.selectedTags);
  state.topics.current.unshift({ id, title: `新议题_${id}`, tags, favorited: false, archived: false });
  renderTopics();
}

function topicItemHTML(t) {
  return `<li class="topic-item" data-id="${t.id}">
    <input class="topic-title" value="${escapeHTML(t.title)}" />
    <div class="topic-actions">
      <button type="button" class="icon-btn fav" data-act="fav" title="收藏">★</button>
      <button type="button" class="icon-btn export" data-act="export" title="导出">⤓</button>
      <button type="button" class="icon-btn archive" data-act="archive" title="归档">🗂️</button>
      <button type="button" class="icon-btn delete" data-act="del" title="删除" ${t.favorited ? 'disabled' : ''}>🗑️</button>
    </div>
  </li>`;
}

function bindTopicItem(el) {
  const id = el.dataset.id;
  const input = $('.topic-title', el);
  // 整块点击也可激活
  el.addEventListener('click', (e) => {
    // 避免与按钮点击冲突
    if (e.target.closest('.topic-actions')) return;
    setActiveTopic(id);
    console.log('[topic] active by card click', id);
  });
  input.addEventListener('click', () => {
    // 单击：设置为当前激活议题并高亮；定位到议题头部（占位）
    setActiveTopic(id);
    console.log('[topic] active & locate to', id);
  });
  input.addEventListener('dblclick', () => input.removeAttribute('readonly'));
  input.addEventListener('blur', () => {
    const t = findTopicById(id);
    if (t) { t.title = input.value.trim() || t.title; }
  });

  const act = (name) => $('.topic-actions [data-act="' + name + '"]', el);
  act('fav').addEventListener('click', (e) => { e.stopPropagation(); toggleFav(id); window.persistUI && window.persistUI(); console.log('[topic] fav toggled', id); });
  act('export').addEventListener('click', (e) => { e.stopPropagation(); exportTopic(id); console.log('[topic] export clicked', id); });
  act('archive').addEventListener('click', (e) => { e.stopPropagation(); toggleArchive(id); window.persistUI && window.persistUI(); console.log('[topic] archive toggled', id); });
  act('del').addEventListener('click', (e) => { e.stopPropagation(); deleteTopic(id); window.persistUI && window.persistUI(); console.log('[topic] deleted', id); });
}

function findTopicById(id) {
  return state.topics.current.find(t => t.id === id) || state.topics.archived.find(t => t.id === id);
}

export function setActiveTopic(id) {
  state.activeTopicId = id;
  // 高亮
  document.querySelectorAll('.topic-item').forEach(el => el.classList.toggle('active', el.dataset.id === id));
}

export function getActiveTopicId() {
  return state.activeTopicId || (state.topics.current[0] && state.topics.current[0].id) || null;
}

function toggleFav(id) {
  const t = findTopicById(id); if (!t) return;
  t.favorited = !t.favorited; renderTopics();
}

function exportTopic(id) {
  // TODO: 调用导出接口：生成 MD + attachments.json（创建时间升序）
  console.log('[export] topic', id);
}

function toggleArchive(id) {
  let from = state.topics.current, to = state.topics.archived;
  let t = from.find(x => x.id === id);
  if (!t) { from = state.topics.archived; to = state.topics.current; t = from.find(x => x.id === id); }
  if (!t) return;
  if (t.favorited) return;
  from.splice(from.indexOf(t), 1);
  t.archived = !t.archived;
  to.unshift(t);
  renderTopics();
}

function deleteTopic(id) {
  const t = findTopicById(id); if (!t || t.favorited) return;
  if (!confirm('确认删除该议题及其所有会话与输出内容？')) return;
  state.topics.current = state.topics.current.filter(x => x.id !== id);
  state.topics.archived = state.topics.archived.filter(x => x.id !== id);
  // 清理该议题相关会话
  state.sessions = state.sessions.filter(s => s.topicId !== id);
  // 清理输出区中属于该议题的 feed 块
  const feed = document.getElementById('output-feed');
  if (feed) {
    Array.from(feed.querySelectorAll('.feed-item')).forEach(item => {
      if (item.dataset.topicId === String(id)) item.remove();
    });
  }
  renderTopics();
  renderSessions();
}

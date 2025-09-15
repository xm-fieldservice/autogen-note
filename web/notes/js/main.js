import { state, uid } from './state.js';
import { renderTopics, addTopicFromSelection, getActiveTopicId, setActiveTopic } from './topics.js';
import { renderTags, bindAddTag, initTagsDemo } from './tags.js';
import { renderSessions } from './sessions.js';
import { bindModes } from './modes.js';
import { initTeamPicker } from './team.js';
import { initAgentPicker } from './agent.js';

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

function bindTabs() {
  $$('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      $$('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const active = btn.dataset.tab;
      $$('.tab-content').forEach(c => c.classList.add('hidden'));
      document.getElementById(`tab-${active}`).classList.remove('hidden');
    });
  });
}

function bindTopicButtons() {
  document.getElementById('btn-add-topic').addEventListener('click', () => addTopicFromSelection());
}

function bindEditors() {
  const wrap = (textarea, wrapper) => {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;
    textarea.value = value.slice(0, start) + wrapper + value.slice(start, end) + wrapper + value.slice(end);
    textarea.focus();
  };
  document.getElementById('btn-input-bold').addEventListener('click', () => wrap(document.getElementById('input-md'), '**'));
  document.getElementById('btn-input-italic').addEventListener('click', () => wrap(document.getElementById('input-md'), '*'));
  document.getElementById('btn-input-copy').addEventListener('click', () => navigator.clipboard.writeText(document.getElementById('input-md').value));
  document.getElementById('btn-input-paste').addEventListener('click', async () => { const t = await navigator.clipboard.readText(); document.getElementById('input-md').value += t; });

  document.getElementById('btn-output-bold').addEventListener('click', () => wrapInFeedSelection('**'));
  document.getElementById('btn-output-italic').addEventListener('click', () => wrapInFeedSelection('*'));
  document.getElementById('btn-output-copy').addEventListener('click', copyFeedAll);

  const inputEl = document.getElementById('input-md');
  // 取消组合键提交，统一改为一次性“提交”按钮
  const submitBtn = document.getElementById('btn-submit');
  submitBtn?.addEventListener('click', oneShotSubmit);

  document.getElementById('file-upload').addEventListener('change', (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    console.log('[upload] files', files.map(f => ({ name: f.name, size: f.size })));
    // TODO: 调用 ingest_file.py
  });
}

let altEnterStage = 0; // 0: 未预处理；1: 已预处理，待落库/查询
function preprocessToOutput() {
  const inputEl = document.getElementById('input-md');
  const text = inputEl.value;
  const agent = document.getElementById('agent-selector')?.value || state.selectedAgent?.name || 'default';
  // TODO: 调用选中的 agent 做预处理。当前占位为直接复制。
  appendFeedItem({ role: 'user', content: text, agent, topicId: getActiveTopicId() });
  // 第一次提交后清空输入框
  inputEl.value = '';
  console.log('[preprocess] via agent =', agent);
}

// 一次性提交逻辑：可选经 Agent 预处理 → 输出区 → 右侧会话列表
async function oneShotSubmit() {
  const inputEl = document.getElementById('input-md');
  const raw = (inputEl?.value || '').trim();
  if (!raw) { inputEl?.focus(); return; }
  const topicId = getActiveTopicId();
  const agentName = state.selectedAgent?.name || '(无Agent)';

  let finalText = raw;
  try {
    const mod = state.selectedAgent?.module;
    if (mod && typeof mod.preprocess === 'function') {
      const context = { topicId, mode: state.activeMode, now: Date.now(), tags: Array.from(state.selectedTags||[]) };
      const out = await mod.preprocess(raw, context);
      if (typeof out === 'string' && out.trim()) finalText = out;
    }
  } catch (err) {
    console.warn('[oneShotSubmit] 预处理失败，使用原文：', err);
  }

  // 写入输出区
  appendFeedItem({ role: 'user', content: finalText, agent: agentName, topicId });

  // 写入右侧会话列表
  const sid = uid();
  state.sessions.unshift({ id: sid, topicId, content: finalText, createdAt: Date.now(), favorited: false });
  renderSessions();

  // 清空输入并持久化
  if (inputEl) inputEl.value = '';
  persistUI();
}

function onAltEnter() {
  if (altEnterStage === 0) {
    preprocessToOutput();
    altEnterStage = 1;
    console.log('[Alt+Enter] 阶段1完成：预处理到输出区');
    return;
  }
  // 以输出区最新块内容作为提交对象
  const latest = getLatestFeedText();
  const content = latest || '';
  const topicId = getActiveTopicId();
  if (!topicId) { console.warn('无议题无法写入'); altEnterStage = 0; return; }
  if (state.activeMode === 'note' || state.activeMode === 'search') {
    const sid = uid();
    state.sessions.unshift({ id: sid, topicId, content, createdAt: Date.now(), favorited: false });
    renderSessions();
    console.log('[DB] 写入占位完成：', state.activeMode, sid);
  } else if (state.activeMode === 'qa') {
    console.log('[QA] 调用 Team/联网查询占位');
    const sid = uid();
    const answer = content + '\n\n> [占位查询结果]';
    appendFeedItem({ role: 'assistant', content: answer, agent: state.selectedTeam?.name || 'team', topicId });
    state.sessions.unshift({ id: sid, topicId, content: answer, createdAt: Date.now(), favorited: false });
    renderSessions();
  }
  altEnterStage = 0;
}

function appendFeedItem({ role, content, agent, topicId }) {
  const feed = document.getElementById('output-feed');
  const time = new Date().toLocaleString();
  const div = document.createElement('div');
  div.className = 'feed-item';
  if (topicId) div.dataset.topicId = String(topicId);
  div.innerHTML = `<div class="meta"><span>${role === 'user' ? '输入/预处理' : '输出/结果'} · ${agent || ''}</span><span>${time}</span></div><div class="content"></div>`;
  const contentEl = div.querySelector('.content');
  contentEl.textContent = content;
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
  persistUI();
}

function getLatestFeedText() {
  const feed = document.getElementById('output-feed');
  const items = feed.querySelectorAll('.feed-item .content');
  if (!items.length) return '';
  return items[items.length - 1].textContent || '';
}

function copyFeedAll() {
  const feed = document.getElementById('output-feed');
  const texts = Array.from(feed.querySelectorAll('.feed-item .content')).map(n => n.textContent || '');
  const joined = texts.join('\n\n');
  navigator.clipboard.writeText(joined);
}

function wrapInFeedSelection(wrapper) {
  // 简化：对最后一个块整体包裹（占位实现）
  const feed = document.getElementById('output-feed');
  const items = feed.querySelectorAll('.feed-item .content');
  if (!items.length) return;
  const last = items[items.length - 1];
  last.textContent = `${wrapper}${last.textContent}${wrapper}`;
}

function initDemoData() {
  const saved = loadUI();
  if (saved) {
    Object.assign(state, saved);
  } else {
    state.topics.current = [
      { id: uid(), title: '项目周报', tags: ['需求', '内部'], favorited: false, archived: false },
      { id: uid(), title: '法规研读', tags: ['法规'], favorited: true, archived: false },
    ];
    state.topics.archived = [];
  }
  // 默认激活第一个议题
  setTimeout(() => setActiveTopic(state.activeTopicId || state.topics.current[0]?.id), 0);
}

function bindTabsHeader() {
  $$('.tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === 'current');
  });
  document.getElementById('tab-current').classList.remove('hidden');
  document.getElementById('tab-archived').classList.add('hidden');
  document.getElementById('tab-tags').classList.add('hidden');
}

function init() {
  bindTabsHeader();
  bindTabs();
  bindModes();
  bindTopicButtons();
  bindEditors();
  initTeamPicker();
  initAgentPicker();
  initDemoData();
  initTagsDemo();
  renderTags();
  renderTopics();
  renderSessions();
}

init();

// 基础持久化（localStorage）
function persistUI() {
  const feed = document.getElementById('output-feed');
  const feedData = Array.from(feed.querySelectorAll('.feed-item')).map(el => ({
    topicId: el.dataset.topicId || null,
    meta: el.querySelector('.meta')?.textContent || '',
    content: el.querySelector('.content')?.textContent || ''
  }));
  const data = {
    topics: state.topics,
    sessions: state.sessions,
    selectedTags: Array.from(state.selectedTags),
    activeMode: state.activeMode,
    activeTab: document.querySelector('.tab.active')?.dataset.tab || 'current',
    activeTopicId: state.activeTopicId || null,
    feed: feedData
  };
  localStorage.setItem('notes_ui_state_v1', JSON.stringify(data));
}

function loadUI() {
  try {
    const raw = localStorage.getItem('notes_ui_state_v1');
    if (!raw) return null;
    const data = JSON.parse(raw);
    state.topics = data.topics || state.topics;
    state.sessions = data.sessions || state.sessions;
    state.selectedTags = new Set(data.selectedTags || []);
    state.activeMode = data.activeMode || state.activeMode;
    state.activeTopicId = data.activeTopicId || state.activeTopicId;
    // 还原 feed
    setTimeout(() => {
      const feed = document.getElementById('output-feed');
      (data.feed || []).forEach(item => {
        appendFeedItem({ role: 'user', content: item.content, agent: '', topicId: item.topicId });
      });
    }, 0);
    return state;
  } catch {
    return null;
  }
}

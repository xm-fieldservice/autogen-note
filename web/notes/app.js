// PC 笔记页面（三库集成原型）占位脚本
// 仅前端原型：实现基本交互、快捷键与占位事件钩子，不接后端。

(function () {
  const $ = (s, p = document) => p.querySelector(s);
  const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

  // 状态（简单内存存储，后续对接 DB）
  const state = {
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

  // 简易ID生成
  const uid = () => Math.random().toString(36).slice(2, 10);

  // 本地存储最近Team
  const RECENT_TEAMS_KEY = 'notes_recent_teams';
  const loadRecentTeams = () => {
    try { state.recentTeams = JSON.parse(localStorage.getItem(RECENT_TEAMS_KEY) || '[]'); } catch { state.recentTeams = []; }
    renderRecentTeams();
  };
  const saveRecentTeam = (path, name) => {
    const exists = state.recentTeams.find(x => x.path === path);
    if (!exists) {
      state.recentTeams.unshift({ path, name, ts: Date.now() });
      state.recentTeams = state.recentTeams.slice(0, 10);
      localStorage.setItem(RECENT_TEAMS_KEY, JSON.stringify(state.recentTeams));
      renderRecentTeams();
    }
  };

  function renderRecentTeams() {
    const sel = $('#recent-teams');
    sel.innerHTML = '<option value="">最近使用…</option>' + state.recentTeams.map(rt => `<option value="${encodeURIComponent(rt.path)}">${rt.name}</option>`).join('');
  }

  // Tab 切换
  function bindTabs() {
    $$('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.activeTab = btn.dataset.tab;
        $$('.tab-content').forEach(c => c.classList.add('hidden'));
        $(`#tab-${state.activeTab}`).classList.remove('hidden');
      });
    });
  }

  // Mode 切换
  function bindModes() {
    $$('.mode-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.activeMode = btn.dataset.mode; // note|search|qa
        console.log('[mode] active =', state.activeMode);
      });
    });
    $('#auto-mode').addEventListener('change', (e) => {
      state.autoMode = !!e.target.checked;
      console.log('[autoMode]', state.autoMode);
    });
  }

  // 议题渲染与操作
  function renderTopics() {
    const lists = {
      current: $('#topic-list-current'),
      archived: $('#topic-list-archived')
    };
    Object.entries(lists).forEach(([key, ul]) => {
      const set = state.topics[key] || [];
      // 标签过滤：仅对 current 列表应用（归档也可应用，暂维持一致性）
      const selectedTags = Array.from(state.selectedTags);
      const filtered = selectedTags.length === 0 ? set : set.filter(t => selectedTags.every(tag => t.tags?.includes(tag)));
      ul.innerHTML = filtered.map(t => topicItemHTML(t)).join('');
    });

    // 绑定事件
    $$('#topic-list-current .topic-item, #topic-list-archived .topic-item').forEach(item => bindTopicItem(item));
  }

  function topicItemHTML(t) {
    const tags = (t.tags || []).map(x => `<span class="tag">${x}</span>`).join(' ');
    return `<li class="topic-item" data-id="${t.id}">
      <input class="topic-title" value="${escapeHTML(t.title)}" title="双击可修改，单击定位" />
      <div class="topic-actions">
        <button class="btn sm secondary" data-act="fav">${t.favorited ? '★' : '☆'}</button>
        <button class="btn sm" data-act="export">导出</button>
        <button class="btn sm" data-act="archive">${t.archived ? '取消归档' : '归档'}</button>
        <button class="btn sm" data-act="del" ${t.favorited ? 'disabled' : ''}>删除</button>
      </div>
    </li>`;
  }

  function bindTopicItem(el) {
    const id = el.dataset.id;
    const input = $('.topic-title', el);
    input.addEventListener('dblclick', () => input.removeAttribute('readonly'));
    input.addEventListener('blur', () => {
      const t = findTopicById(id);
      if (t) { t.title = input.value.trim() || t.title; }
    });
    input.addEventListener('click', () => {
      // 单击定位议题头部（占位）
      console.log('[topic] locate to', id);
    });

    $('.topic-actions [data-act="fav"]', el).addEventListener('click', () => toggleFav(id));
    $('.topic-actions [data-act="export"]', el).addEventListener('click', () => exportTopic(id));
    $('.topic-actions [data-act="archive"]', el).addEventListener('click', () => toggleArchive(id));
    $('.topic-actions [data-act="del"]', el).addEventListener('click', () => deleteTopic(id));
  }

  function findTopicById(id) {
    return state.topics.current.find(t => t.id === id) || state.topics.archived.find(t => t.id === id);
  }

  function toggleFav(id) {
    const t = findTopicById(id); if (!t) return;
    t.favorited = !t.favorited; renderTopics();
  }

  function exportTopic(id) {
    // 占位：导出文本+附件清单（由后端/脚本处理）。
    console.log('[export] topic', id, 'TODO: 调用导出接口');
  }

  function toggleArchive(id) {
    let from = state.topics.current, to = state.topics.archived;
    let t = from.find(x => x.id === id);
    if (!t) { from = state.topics.archived; to = state.topics.current; t = from.find(x => x.id === id); }
    if (!t) return;
    if (t.favorited) return;
    // 移动
    from.splice(from.indexOf(t), 1);
    t.archived = !t.archived;
    to.unshift(t);
    renderTopics();
  }

  function deleteTopic(id) {
    const t = findTopicById(id); if (!t || t.favorited) return;
    state.topics.current = state.topics.current.filter(x => x.id !== id);
    state.topics.archived = state.topics.archived.filter(x => x.id !== id);
    renderTopics();
  }

  // 新增议题（继承已选标签）
  $('#btn-add-topic').addEventListener('click', () => {
    const id = uid();
    const tags = Array.from(state.selectedTags);
    state.topics.current.unshift({ id, title: `新议题_${id}`, tags, favorited: false, archived: false });
    renderTopics();
  });

  // 标签管理
  const tagSet = new Set();
  function renderTags() {
    const ul = $('#tag-list');
    const all = Array.from(tagSet);
    ul.innerHTML = all.map(tag => `<li class="tag-item"><label><input type="checkbox" data-tag="${tag}" ${state.selectedTags.has(tag) ? 'checked' : ''}/> ${tag}</label><button class="btn sm secondary" data-del="${tag}">删</button></li>`).join('');
    // 绑定
    $$('#tag-list input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', () => {
        const tag = cb.dataset.tag;
        if (cb.checked) state.selectedTags.add(tag); else state.selectedTags.delete(tag);
        renderTopics();
      });
    });
    $$('#tag-list [data-del]').forEach(btn => {
      btn.addEventListener('click', () => { tagSet.delete(btn.dataset.del); state.selectedTags.delete(btn.dataset.del); renderTags(); renderTopics(); });
    });
  }
  $('#btn-add-tag').addEventListener('click', () => {
    const name = $('#input-new-tag').value.trim();
    if (!name) return;
    tagSet.add(name);
    $('#input-new-tag').value = '';
    renderTags();
  });

  // Team 选择器（占位）
  $('#btn-pick-team').addEventListener('click', () => $('#team-file').click());
  $('#team-file').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.selectedTeam = { name: file.name, path: file.name };
    saveRecentTeam(file.name, file.name);
    console.log('[team] selected', state.selectedTeam);
  });
  $('#recent-teams').addEventListener('change', (e) => {
    const val = e.target.value; if (!val) return;
    const path = decodeURIComponent(val);
    const item = state.recentTeams.find(x => x.path === path);
    if (item) state.selectedTeam = { name: item.name, path: item.path };
    console.log('[team] selected recent', state.selectedTeam);
  });

  // 输入/输出编辑工具（简单占位）
  function wrapSelectionTextArea(textarea, wrapper) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;
    textarea.value = value.slice(0, start) + wrapper + value.slice(start, end) + wrapper + value.slice(end);
    textarea.focus();
  }
  $('#btn-input-bold').addEventListener('click', () => wrapSelectionTextArea($('#input-md'), '**'));
  $('#btn-input-italic').addEventListener('click', () => wrapSelectionTextArea($('#input-md'), '*'));
  $('#btn-input-copy').addEventListener('click', () => { navigator.clipboard.writeText($('#input-md').value); });
  $('#btn-input-paste').addEventListener('click', async () => { const t = await navigator.clipboard.readText(); $('#input-md').value += t; });

  $('#btn-output-bold').addEventListener('click', () => wrapSelectionTextArea($('#output-md'), '**'));
  $('#btn-output-italic').addEventListener('click', () => wrapSelectionTextArea($('#output-md'), '*'));
  $('#btn-output-copy').addEventListener('click', () => { navigator.clipboard.writeText($('#output-md').value); });

  // 快捷键：Enter换行；Shift+Enter预处理；Alt+Enter两步提交
  const inputEl = $('#input-md');
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.shiftKey) {
      e.preventDefault();
      // 预处理 → 输出区（不落库），可由整理Agent或选中Team处理
      preprocessToOutput();
    } else if (e.key === 'Enter' && e.altKey) {
      e.preventDefault();
      onAltEnter();
    } else if (e.key === 'Enter' && !e.shiftKey && !e.altKey) {
      // 普通换行，默认行为
    }
  });

  function preprocessToOutput() {
    const text = $('#input-md').value;
    // TODO: 根据 state.activeMode 与 state.autoMode 调用“意图识别/整理 Agent 或 Team”
    // 目前占位：直接拷贝到输出区
    $('#output-md').value = text;
    console.log('[preprocess] done (placeholder)');
  }

  let altEnterStage = 0; // 0→第一次预处理；1→第二次落库/查询
  function onAltEnter() {
    if (altEnterStage === 0) {
      preprocessToOutput();
      altEnterStage = 1;
      console.log('[Alt+Enter] 阶段1完成：已预处理到输出区（不落库）');
    } else {
      // 阶段2：根据模式执行落库或查询
      const content = $('#output-md').value;
      const topicId = state.topics.current[0]?.id || null; // 占位：选择当前第一个议题
      if (!topicId) {
        console.warn('无议题，无法写入');
        return;
      }
      if (state.activeMode === 'note' || state.activeMode === 'search') {
        // DB 落库占位
        const sid = uid();
        state.sessions.unshift({ id: sid, topicId, content, createdAt: Date.now(), favorited: false });
        renderSessions();
        console.log('[DB] 写入占位完成：note/search', { sid, topicId });
      } else if (state.activeMode === 'qa') {
        // 问答查询占位
        console.log('[QA] 调用 Team/联网查询占位，随后写入DB…');
        const sid = uid();
        state.sessions.unshift({ id: sid, topicId, content: content + '\n\n> [占位查询结果]', createdAt: Date.now(), favorited: false });
        renderSessions();
      }
      altEnterStage = 0;
    }
  }

  // 会话列表渲染与操作
  function renderSessions() {
    const ul = $('#session-list');
    ul.innerHTML = state.sessions.map(s => `<li class="session-item" data-id="${s.id}">
      <div class="session-content">${escapeHTML(s.content.slice(0, 200))}</div>
      <div class="session-actions">
        <button class="btn sm secondary" data-act="fav">${s.favorited ? '★' : '☆'}</button>
        <button class="btn sm" data-act="copy">复制</button>
        <button class="btn sm" data-act="del">删除</button>
      </div>
    </li>`).join('');

    $$('#session-list .session-item').forEach(item => {
      const id = item.dataset.id;
      $('[data-act="fav"]', item).addEventListener('click', () => { const s = state.sessions.find(x => x.id === id); if (s) { s.favorited = !s.favorited; renderSessions(); }});
      $('[data-act="copy"]', item).addEventListener('click', () => { const s = state.sessions.find(x => x.id === id); if (s) navigator.clipboard.writeText(s.content); });
      $('[data-act="del"]', item).addEventListener('click', () => { const s = state.sessions.find(x => x.id === id); if (!s) return; state.sessions = state.sessions.filter(x => x.id !== id); renderSessions(); });
      item.addEventListener('click', (e) => {
        if (e.target.closest('.session-actions')) return;
        const s = state.sessions.find(x => x.id === id); if (s) $('#output-md').value = s.content; // 定位到输出区
      });
    });
  }

  // 附件上传（占位）
  $('#file-upload').addEventListener('change', (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    // TODO: 调用 ingest_file.py，通过 MCP 入库（原样归档+指针），策略字段由 UI 决策写入
    console.log('[upload] files =', files.map(f => ({ name: f.name, size: f.size })));
  });

  function escapeHTML(s) {
    return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function initDemoData() {
    // 初始标签
    ['需求', '规划', '法规', '内部'].forEach(t => tagSet.add(t));
    // 初始议题
    state.topics.current = [
      { id: uid(), title: '项目周报', tags: ['需求', '内部'], favorited: false, archived: false },
      { id: uid(), title: '法规研读', tags: ['法规'], favorited: true, archived: false },
    ];
    state.topics.archived = [];
  }

  function init() {
    bindTabs();
    bindModes();
    initDemoData();
    renderRecentTeams();
    renderTags();
    renderTopics();
    renderSessions();
    loadRecentTeams();
  }

  init();
})();

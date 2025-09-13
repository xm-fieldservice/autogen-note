import { state } from './state.js';
import { renderTopics } from './topics.js';

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

// 标签集合（内存原型）
export const tagSet = new Set();

export function initTagsDemo() {
  ['需求', '规划', '法规', '内部'].forEach(t => tagSet.add(t));
}

export function renderTags() {
  const ul = $('#tag-list');
  const all = Array.from(tagSet);
  ul.innerHTML = all.map(tag => `<li class="tag-item"><label><input type="checkbox" data-tag="${tag}" ${state.selectedTags.has(tag) ? 'checked' : ''}/> ${tag}</label><button class="btn sm secondary" data-del="${tag}">删</button></li>`).join('');

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

export function bindAddTag() {
  $('#btn-add-tag').addEventListener('click', () => {
    const name = $('#input-new-tag').value.trim();
    if (!name) return;
    tagSet.add(name);
    $('#input-new-tag').value = '';
    renderTags();
  });
}

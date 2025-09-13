import { state } from './state.js';

const $ = (s, p = document) => p.querySelector(s);
const $$ = (s, p = document) => Array.from(p.querySelectorAll(s));

export function bindModes() {
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

// ==UserScript==
// @name         Crunchy Local — Crunchyroll sign-in
// @namespace    crunchy-local
// @version      1.0.4
// @description  Connect your official Crunchyroll session to your own Crunchy Local player.
// @grant        unsafeWindow
// @match        http://127.0.0.1/*
// @match        http://localhost/*
// @match        https://www.crunchyroll.com/*
// @grant        GM_cookie
// @grant        GM_openInTab
// @run-at       document-idle
// @noframes
// ==/UserScript==

(() => {
  'use strict';
  const ALLOWED_PLAYER_ORIGINS = new Set(["http://127.0.0.1:8765", "http://localhost:8765"]);
  if (window.top !== window.self || !ALLOWED_PLAYER_ORIGINS.has(location.origin)) return;
  const source = 'crunchy-local-extension';
  const provider = 'tampermonkey';
  const english = !String(document.documentElement.lang || navigator.language).toLowerCase().startsWith('ru');
  const text = (en, ru) => english ? en : ru;
  let active = false;
  let stopped = false;
  const send = (type, extra = {}) => window.postMessage(JSON.stringify({source, provider, type, ...extra}), location.origin);
  function cookie() {
    return new Promise((resolve, reject) => {
      if (typeof GM_cookie === 'undefined' || typeof GM_cookie.list !== 'function') {
        reject(new Error(text('Tampermonkey cannot read cookies. Enable GM_cookie and HttpOnly cookie access, or use Tampermonkey Beta.', 'Tampermonkey не может читать cookies. Разрешите GM_cookie и доступ к HttpOnly-cookie либо используйте Tampermonkey Beta.')));
        return;
      }
      let settled = false;
      const finish = (error, value = '') => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (error) reject(error); else resolve(value);
      };
      const timer = setTimeout(() => finish(new Error(text(
        'Tampermonkey did not respond to the cookie request. Use Tampermonkey Beta for HttpOnly access. In its dashboard: Settings → Config mode: Advanced → Security → Allow scripts to access cookies: All. Then reload the player.',
        'Tampermonkey не ответил на запрос cookie. Для доступа к HttpOnly используйте Tampermonkey Beta. В панели менеджера: Settings → Config mode: Advanced → Security → Allow scripts to access cookies: All. Затем обновите плеер.'
      ))), 8000);
      try {
        GM_cookie.list({url: 'https://www.crunchyroll.com/', name: 'etp_rt'}, (cookies, error) => {
          if (error) { finish(new Error(text('Allow cookie access in Tampermonkey: Settings → Config mode: Advanced → Security → Allow scripts to access cookies: All.', 'Разрешите доступ к cookie в Tampermonkey: Settings → Config mode: Advanced → Security → Allow scripts to access cookies: All.'))); return; }
          finish(null, (cookies || []).find(item => item.name === 'etp_rt')?.value || '');
        });
      } catch { finish(new Error(text('Tampermonkey cookie access failed. Use Tampermonkey Beta and enable cookie access in its security settings.', 'Tampermonkey не смог прочитать cookie. Используйте Tampermonkey Beta и разрешите доступ к cookie в настройках безопасности.'))); }
    });
  }
  async function login() {
    if (active) return;
    active = true;
    stopped = false;
    let value = '';
    try {
      send('CHECKING');
      value = await cookie();
      if (!value) {
        GM_openInTab('https://www.crunchyroll.com/login', {active: true, insert: true});
        send('WAITING');
        const deadline = Date.now() + 5 * 60_000;
        while (!value && !stopped && Date.now() < deadline) {
          await new Promise(resolve => setTimeout(resolve, 1500));
          if (!stopped) value = await cookie();
        }
        if (stopped) return;
        if (!value) throw new Error(text('Session not found. Complete official sign-in and allow HttpOnly cookie access in Tampermonkey; some versions require Tampermonkey Beta.', 'Сеанс не найден. Завершите официальный вход и разрешите доступ к HttpOnly-cookie в Tampermonkey; в некоторых версиях нужен Tampermonkey Beta.'));
      }
      send('CONNECTING');
      const response = await fetch('/api/connect', {
        method: 'POST', credentials: 'same-origin',
        headers: {'X-Local-Player': '1', 'Content-Type': 'application/json'},
        body: JSON.stringify({cookie: value})
      });
      value = '';
      const result = await response.json();
      if (!response.ok || !result.connected) throw new Error(result.error || text('Could not connect Crunchyroll.', 'Не удалось подключить Crunchyroll.'));
      send('CONNECTED');
    } catch (error) {
      send('ERROR', {message: error.message || text('Sign-in failed.', 'Ошибка входа.')});
    } finally { value = ''; active = false; }
  }
  window.addEventListener('pagehide', () => { stopped = true; });
  window.addEventListener('message', event => {
    const pageWindow = typeof unsafeWindow === 'undefined' ? window : unsafeWindow;
    if ((event.source !== window && event.source !== pageWindow) || event.origin !== location.origin) return;
    // String messages cross Firefox's userscript sandbox without object wrappers.
    if (typeof event.data !== 'string' || event.data.length > 1000) return;
    let message;
    try { message = JSON.parse(event.data); } catch { return; }
    if (message?.source !== 'crunchy-local-page') return;
    if (message.type === 'PING') send('READY');
    if (message.type === 'USERSCRIPT_LOGIN') login();
  });
  send('READY');
})();

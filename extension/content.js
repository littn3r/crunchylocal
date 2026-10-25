const extensionAPI = globalThis.browser || globalThis.chrome;
const ALLOWED_PAGE_ORIGINS = new Set(["http://127.0.0.1:8765", "http://localhost:8765"]);
if (ALLOWED_PAGE_ORIGINS.has(location.origin)) {
const PAGE_SOURCE = 'crunchy-local-page';
const EXTENSION_SOURCE = 'crunchy-local-extension';
let loginActive = false;

function send(type, extra = {}) {
  window.postMessage({ source: EXTENSION_SOURCE, type, ...extra }, location.origin);
}

async function command(type) {
  const result = await extensionAPI.runtime.sendMessage({ type });
  if (result?.error) throw new Error(result.error);
  return result || {};
}

async function importSession(value) {
  const response = await fetch('/api/connect', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-Local-Player': '1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie: value }),
  });
  let result = {};
  try { result = await response.json(); } catch {}
  if (!response.ok || !result.connected) throw new Error(result.error || 'Не удалось подключить сеанс Crunchyroll.');
  send('CONNECTED');
}

async function beginLogin() {
  if (loginActive) return;
  loginActive = true;
  try {
    let cookie = (await command('GET_SESSION')).value;
    if (!cookie) {
      await command('OPEN_LOGIN');
      send('WAITING');
      const deadline = Date.now() + 5 * 60_000;
      while (!cookie && Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        cookie = (await command('GET_SESSION')).value;
      }
      if (!cookie) throw new Error('Время входа истекло. Попробуйте снова.');
    }
    send('CONNECTING');
    await importSession(cookie);
  } catch (error) {
    send('ERROR', { message: error?.message || 'Не удалось войти в Crunchyroll.' });
  } finally {
    loginActive = false;
  }
}

window.addEventListener('message', (event) => {
  if (event.source !== window || event.origin !== location.origin || event.data?.source !== PAGE_SOURCE) return;
  if (event.data.type === 'PING') send('READY');
  if (event.data.type === 'LOGIN') beginLogin();
});
send('READY');

}

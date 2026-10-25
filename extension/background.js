const extensionAPI = globalThis.browser || globalThis.chrome;
const ALLOWED_ORIGINS = new Set(["http://127.0.0.1:8765", "http://localhost:8765"]);

extensionAPI.runtime.onMessage.addListener((message, sender, reply) => {
  let origin;
  try { origin = new URL(sender.url).origin; } catch { return; }
  if (!sender.tab || !ALLOWED_ORIGINS.has(origin)) return;
  (async () => {
    if (message?.type === 'GET_SESSION') {
      const cookie = await extensionAPI.cookies.get({ url: 'https://www.crunchyroll.com/', name: 'etp_rt', ...(sender.tab.cookieStoreId ? {storeId: sender.tab.cookieStoreId} : {}) });
      return { value: cookie?.value || '' };
    }
    if (message?.type === 'OPEN_LOGIN') {
      await extensionAPI.tabs.create({ url: 'https://www.crunchyroll.com/login', ...(sender.tab.cookieStoreId ? {cookieStoreId: sender.tab.cookieStoreId} : {}) });
      return { ok: true };
    }
    return { error: 'Неизвестная команда.' };
  })().then(reply, (error) => reply({ error: error?.message || 'Ошибка расширения.' }));
  return true;
});

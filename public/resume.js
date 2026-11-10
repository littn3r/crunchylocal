/* Client-side playback state: stores the last selected episode in browser storage. */
(function (root) {
  const KEY = 'crunchy-last-episode';
  const id = (value) => typeof value === 'string' && /^[A-Za-z0-9_-]{4,40}$/.test(value);
  const normalize = (value) => {
    if (!value || !id(value.seriesId) || !id(value.episodeId) || !id(value.seasonId)) return null;
    return { seriesId: value.seriesId, seasonId: value.seasonId, episodeId: value.episodeId,
      shikiId: Math.max(0, Number(value.shikiId) || 0), shikiTitle: String(value.shikiTitle || '').slice(0,180),
      time: Number.isFinite(value.time) ? Math.max(0, value.time) : 0 };
  };
  const read = (storage) => { try { return normalize(JSON.parse(storage.getItem(KEY))); } catch { return null; } };
  const write = (storage, value) => { const clean = normalize(value); if (clean) { try { storage.setItem(KEY, JSON.stringify(clean)); } catch {} } };
  const matchingTime = (storage, episodeId) => { const last = read(storage); return last?.episodeId === episodeId ? last.time : 0; };
  const api = { read, write, matchingTime };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CrunchyResume = api;
})(typeof window !== 'undefined' ? window : globalThis);

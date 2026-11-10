/* Persist subtitle language preference across episodes rather than episode-specific track IDs. */
(() => {
  const key = 'crunchy-subtitle-language';
  function normalize(value) {
    if (typeof value !== 'string') return null;
    const language = value.trim().replace(/_/g, '-').toLowerCase();
    return language === 'off' || /^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/.test(language) ? language : null;
  }
  function read(storage) {
    try { return normalize(storage.getItem(key)); } catch { return null; }
  }
  function write(storage, language) {
    const value = normalize(language);
    if (value) { try { storage.setItem(key, value); } catch { /* Storage may be unavailable in private browsing. */ } }
  }
  function choose(tracks, preferred) {
    const language = normalize(preferred);
    if (!language) return null;
    if (language === 'off') return 'off';
    const available = tracks.filter(track => normalize(track.language) && normalize(track.language) !== 'off');
    const match = available.find(track => normalize(track.language) === language)
      || available.find(track => normalize(track.language).split('-')[0] === language.split('-')[0]);
    // Keep the preference when an episode lacks that language, but do not choose another language silently.
    return match ? String(match.id) : 'off';
  }
  const api = {read, write, choose};
  if (typeof window !== 'undefined') window.SubtitlePreference = api;
  if (typeof module !== 'undefined') module.exports = api;
})();

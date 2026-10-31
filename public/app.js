const $ = (id) => document.getElementById(id);
let extensionAvailable = false;
let loginIntegration = 'extension';
const savedSubtitleSize = Number(localStorage.getItem('crunchy-subtitle-size'));
const savedSubtitlePosition = Number(localStorage.getItem('crunchy-subtitle-position'));
const state = {
  infoSeries:null, infoSeq:0, seasonInfoSeq:0, seasonInfo:null,
  connected: false, view: 'discover', series: null, seasons: [], episodes: [], episode: null,
  player: null, keepAlive: null, searchSeq: 0, searchTimer: null, query: '', genre: '', age: '', year: '',
  sort: 'popular', offset: 0, total: 0, pageSize: 36, featured: null, featuredItems: [], featuredIndex: 0, featuredTimer: null, currentSeason: null,
  shikiStatus: { one: {}, rip: {}, mal: {} }, shikiItems: { one: null, rip: null, mal: null },
  provider: ['one','rip','mal'].includes(localStorage.getItem('shiki-provider')) ? localStorage.getItem('shiki-provider') : 'one',
  listFilter: '', shikiTarget: 0, forcedShikiId: 0, forcedShikiTitle: '', currentRate: null, watchedKey: '', shikiRenderSeq: 0,
  seasonMatch: null, seasonRatingId: 0,
  crunchyRating: null, ratingsSeq: 0,
  relatedSeq: 0, controlsTimer: null, playbackErrorTimer: null, settingsSection: '', lastMediaTime: 0,
  playbackRecoveryAttempts: 0, recoveringPlayback: false, recoveryTime: 0,
  mini: false, sidebarCollapsed: false, audioLocale: '', audioSwitching: false,
  assTracks: new Map(), assCache: new Map(), assRenderer: null, assTrackId: '', assContent: '', assPositionKey: '', subtitleSeq: 0,
  subtitleScale: [0.75, 0.9, 1, 1.1, 1.25, 1.5].includes(savedSubtitleSize) ? savedSubtitleSize : 1,
  subtitlePosition: [1, 2, 4, 6, 10].includes(savedSubtitlePosition) ? savedSubtitlePosition : 2
};
state.listScoreObserver = null;
state.scoreQueue = [];
state.scoreLoading = 0;
state.scoreCache = new Map();
const video = $('video');
$('subtitle-size').value = String(state.subtitleScale);
$('subtitle-size-summary').textContent = `${Math.round(state.subtitleScale * 100)}%`;
$('subtitle-position').value = String(state.subtitlePosition);
$('sidebar-address').textContent = I18n.t("Локальный плеер · {0}",location.hostname);
const providerLabel = (provider) => provider === 'mal' ? 'MyAnimeList' : provider === 'rip' ? new URL(state.shikiStatus.rip?.host || 'https://shikimori.rip').hostname : 'shikimori.io';
const providerHost = (provider) => provider === 'mal' ? 'https://myanimelist.net' : provider === 'rip' ? (state.shikiStatus.rip?.host || 'https://shikimori.rip') : 'https://shikimori.io';
const seasonMapKey = (provider, seriesId, seasonId) => `shiki-season:${provider}:${seriesId}:${seasonId}`;
const currentSeasonRecord = () => state.seasons.find((season) => season.id === state.currentSeason);
function seasonLabel(season, index = 0) {
  const base = state.series?.title?.trim() || I18n.t("Аниме");
  if (!season) return base;
  const title = season?.title?.trim() || '';
  const generic = /^(?:season|сезон)\s*(\d+)$/i.exec(title);
  const number = generic?.[1] || season?.season_number || season?.season_sequence_number || Math.max(1, index + 1);
  const repeated = title && state.seasons.filter((item) => item.title?.trim().toLowerCase() === title.toLowerCase()).length > 1;
  const compact = (value) => value.toLowerCase().replace(/[^a-z0-9]/g, '');
  const numberedBase = compact(title) === compact(base + number);
  if (!title || generic || numberedBase || repeated || (state.seasons.length > 1 && title.toLowerCase() === base.toLowerCase())) {
    return I18n.t("{0} · Сезон {1}",base,number);
  }
  return title;
}
function selectedShikiSeason() {
  const id = state.shikiTarget || state.seasonRatingId || state.seasonMatch?.matched_id;
  return state.seasonMatch?.items.find((item) => item.mal_id === id) || null;
}
function currentSeasonTitle() {
  const season = currentSeasonRecord();
  const title = season?.title?.trim();
  const matched = selectedShikiSeason();
  const generic = !title || /^(?:season|сезон)\s*\d+$/i.test(title) || title.toLowerCase().replace(/[^a-z0-9]/g, '') === `${state.series?.title || ''}${season?.season_number || ''}`.toLowerCase().replace(/[^a-z0-9]/g, '');
  const matchedTitle = matched?.english_title?.trim() || '';
  const matchedIsNumberedBase = matchedTitle.toLowerCase().replace(/[^a-z0-9]/g, '') === `${state.series?.title || ''}${season?.season_number || ''}`.toLowerCase().replace(/[^a-z0-9]/g, '');
  if (generic && matchedTitle && !/^(?:season|сезон)\s*\d+$/i.test(matchedTitle)
      && !matchedIsNumberedBase && matchedTitle.toLowerCase() !== (state.series?.title || '').toLowerCase()) return matchedTitle;
  return seasonLabel(season, state.seasons.indexOf(season));
}
function currentSeasonPoster() {
  const info=state.seasonInfo;
  if(info?.season===state.currentSeason && info.id===seasonInformationId() && info.data.poster)return info.data.poster;
  const season=currentSeasonRecord();
  return selectedShikiSeason()?.poster || season?.images?.poster_tall?.[0]?.at(-1)?.source || state.series?.poster || state.series?.wide || '';
}
function setPoster(image, source, fallback = '') {
  if (/\/assets\/globals\/missing_/.test(source || '')) source = '';
  if (/\/assets\/globals\/missing_/.test(fallback)) fallback = '';
  source = source || fallback;
  if (source && image.getAttribute('src') === source) return;
  image.dataset.fallback = fallback && fallback !== source ? fallback : '';
  image.style.opacity = '';
  image.src = source || fallback || '';
}
function updateSeasonPresentation() {
  const series = state.series;
  if (!series) return;
  const season = currentSeasonRecord();
  const title = currentSeasonTitle();
  const number = episodeNumber();
  $('series-title').textContent = state.episode
    ? I18n.t("Серия {0}{1}",number || '—',state.episode.title ? ` — ${state.episode.title}` : '') : title;
  $('watch-season-name').textContent = title;
  setPoster($('watch-season-poster'), currentSeasonPoster(), series.poster || series.wide || '');
  $('watch-season-poster').alt = I18n.t("Обложка сезона «{0}»",title);
  const count = state.episodes.length || season?.number_of_episodes || 0;
  $('series-meta').textContent = [series.year, count ? I18n.t("{0} серий",count) : '', series.age_rating ? ageLabel(series.age_rating) : ''].filter(Boolean).join(' · ');
  $('season-page-title').textContent = title;
  setPoster($('season-page-poster'), currentSeasonPoster(), series.poster || series.wide || '');
  $('season-page-poster').alt = I18n.t("Обложка сезона «{0}»",title);
  $('season-page-meta').textContent = [series.title !== title ? series.title : '', series.year, count ? I18n.t("{0} серий",count) : '', series.age_rating ? ageLabel(series.age_rating) : ''].filter(Boolean).join(' · ');
  $('season-page-description').textContent = season?.description || series.description || '';
  $('season-page-count').textContent = count ? I18n.t("{0} серий",count) : I18n.t("Серии пока недоступны");
  $('season-play-first').disabled = !state.episodes.length;
  if(state.seasonInfo?.season===state.currentSeason && state.seasonInfo.id===seasonInformationId())applyInformationHero('season-page',state.seasonInfo.data);
}
function renderSeasonEpisodes() {
  $('season-page-episodes').innerHTML = state.episodes.map((ep, index) => {
    const meta = ep.episode_metadata || {};
    const image = ep.images?.thumbnail?.[0]?.at(-1)?.source || ep.images?.poster_wide?.[0]?.at(-1)?.source || '';
    return I18n.html(`<button class="season-page-episode" type="button" data-id="${escapeHtml(ep.id)}"><span class="season-page-thumb">${image ? `<img src="${escapeHtml(image)}" alt="" loading="lazy">` : icon('play_arrow')}</span><span class="season-page-episode-copy"><span>Серия ${escapeHtml(meta.episode || meta.episode_number || index + 1)}</span><strong>${escapeHtml(ep.title || I18n.t("Серия {0}",index + 1))}</strong><small>${escapeHtml(ep.description || '')}</small></span></button>`);
  }).join('') || I18n.html('<div class="episodes-status">Серии этого сезона пока недоступны.</div>');
  $('season-page-episodes').querySelectorAll('.season-page-episode').forEach((card) => card.addEventListener('click', () => { showView('watch'); selectEpisode(card.dataset.id); }));
}
const ageLabel = (age) => ({ ALL: I18n.t("Для всех"), PG: 'PG', '12': '12+', '14': '14+', '16': '16+', '18': '18+', unrated: I18n.t("Не указан") }[age] || age);
const statusLabel = (status) => ({ planned: I18n.t("Планирую"), watching: I18n.t("Смотрю"), rewatching: I18n.t("Пересматриваю"), completed: I18n.t("Просмотрено"), on_hold: I18n.t("Отложено"), dropped: I18n.t("Брошено") }[status] || status);
function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])); }
document.addEventListener('error', (event) => {
  const image = event.target;
  if (!(image instanceof HTMLImageElement) || image.id === 'feature-image') return;
  if(image.classList.contains('character-image')) {
    image.outerHTML=`<span class="character-placeholder">${icon('person')}</span>`;return;
  }
  for (const key of ['fallback','fallback2']) {
    const fallback=image.dataset[key];delete image.dataset[key];
    if(fallback && fallback!==image.src && !/\/assets\/globals\/missing_/.test(fallback)) {
      image.style.opacity='';image.src=fallback;return;
    }
  }
  image.style.opacity = '0';
}, true);
function icon(name) { return `<span class="mi" aria-hidden="true">${name}</span>`; }
function formatTime(seconds) { if (!Number.isFinite(seconds)) return '0:00'; const s = Math.floor(seconds); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
async function api(path, options = {}) {
  const headers = { 'X-Local-Player': '1', ...(options.headers || {}) };
  if (options.body && typeof options.body !== 'string') { options.body = JSON.stringify(options.body); headers['Content-Type'] = 'application/json'; }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let data;
  try { data = JSON.parse(text); } catch { throw new Error(I18n.t("Сервер не вернул данные. Проверьте соединение и повторите попытку.")); }
  if (!response.ok) throw new Error(I18n.translate(data.error) || I18n.t("Не удалось загрузить данные."));
  if(I18n.language==='en' && Array.isArray(data.items))data.items.forEach(item=>{if(item.title_en)item.title=item.title_en;});
  return data;
}
function playerMessage(text) { $('player-message').textContent = text; $('player-message').classList.remove('hidden'); showPlayerControls(); }
function clearPlayerMessage() { clearTimeout(state.playbackErrorTimer); $('player-message').classList.add('hidden'); }
function shikiMessage(text, error = false) { $('shiki-sync-status').textContent = text; $('shiki-sync-status').style.color = error ? '#ffad97' : ''; }
function setConnected(value) {
  state.connected = value;
  $('account-button').innerHTML = `${icon(value ? 'check_circle' : 'account_circle')}<span class="header-label">Crunchyroll</span>`;
  $('account-button').setAttribute('aria-label', value ? I18n.t("Crunchyroll подключён: настройки аккаунта") : I18n.t("Войти в Crunchyroll"));
  $('remote-login-card').classList.toggle('hidden', value);
  const mobile = /Android|iPhone|iPad/i.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(navigator.userAgent));
  $('disconnect-button').classList.toggle('hidden', !value);
  $('extension-ready').classList.toggle('hidden', value || !extensionAvailable);
  $('extension-ready').querySelector('strong').textContent = I18n.t(loginIntegration === 'tampermonkey' ? 'Скрипт Tampermonkey установлен' : 'Расширение установлено');
  $('extension-install').classList.toggle('hidden', value || extensionAvailable || mobile);
  const firefox = /Firefox\//.test(navigator.userAgent);
  $('extension-install-chromium').classList.toggle('hidden', firefox);
  $('cookie-fallback').classList.toggle('hidden', value);
  $('account-title').textContent = value ? I18n.t("Crunchyroll подключён") : I18n.t("Войти в Crunchyroll");
  $('account-description').textContent = value ? I18n.t("Сезоны, серии и видео доступны в плеере.") : I18n.t("Откройте официальный вход внутри плеера. На компьютере также доступно расширение.");
}
function setProvider(provider) {
  if (!['one', 'rip', 'mal'].includes(provider)) return;
  const changed = state.provider !== provider;
  state.provider = provider;
  if(changed) {
    state.seasonMatch=null;state.seasonRatingId=0;
    if(state.series) {
      setPoster($('cover-image'),state.series.poster || state.series.wide || '');
      updateSeasonPresentation();
      if(state.currentSeason)resolveSeasonMatch(state.currentSeason).then(renderShikiControls);
    }
  }
  localStorage.setItem('shiki-provider', provider);
  $('list-provider').value = provider;
  $('shiki-provider-select').value = provider;
  syncSiteSelect('list-provider'); syncSiteSelect('shiki-provider-select');
  updateShikiStatusUI();
  if (state.view === 'list') saveRoute();
}
function saveRoute() {
  const params = new URLSearchParams();
  if (state.view === 'list') {
    params.set('view', 'list');
    params.set('provider', state.provider);
  } else if (state.view === 'info' && state.infoSeries?.id) {
    params.set('view','info');params.set('series',state.infoSeries.id);
  } else if ((state.view === 'watch' || state.view === 'season') && state.series?.id) {
    params.set('view', state.view);
    params.set('series', state.series.id);
    if (state.currentSeason) params.set('season', state.currentSeason);
    if (state.episode?.id) params.set('episode', state.episode.id);
    if (seasonInformationId()) params.set('shiki_id', String(seasonInformationId()));
    const seasonTitle=currentSeasonRecord()?.title || state.forcedShikiTitle;
    if (seasonTitle) params.set('shiki_title', seasonTitle);
  }
  const next = location.pathname + (params.size ? '?' + params : '');
  if (location.pathname + location.search !== next) history.replaceState(null, '', next);
}
function updateShikiStatusUI() {
  const info = state.shikiStatus[state.provider] || {};
  $('shiki-button').innerHTML = `${icon('view_list')}<span class="header-label">${escapeHtml(info.connected ? info.name || providerLabel(state.provider) : (state.provider==='mal' ? 'MAL' : 'Shikimori'))}</span>`;
  $('shiki-button').setAttribute('aria-label', info.connected ? I18n.t("{0}: настройки аккаунта",info.name || providerLabel(state.provider)) : I18n.t("Подключить список"));
  $('shiki-mirror-field').classList.toggle('hidden', state.provider !== 'rip');
  $('shiki-mirror-select').value = state.shikiStatus.rip?.host || 'https://shikimori.rip';
  syncSiteSelect('shiki-mirror-select');
  $('shiki-account-status').textContent = info.connected ? I18n.t("Подключён аккаунт {0} на {1}",info.name || '',providerLabel(state.provider)) : info.configured ? I18n.t("Вход для {0} готов. Логин и пароль вводятся на официальном сайте.",providerLabel(state.provider)) : I18n.t("OAuth-приложение для {0} не настроено.",providerLabel(state.provider));
  $('shiki-disconnect').classList.toggle('hidden', !info.connected);
  $('mal-registration').classList.toggle('hidden',state.provider!=='mal' || info.configured);
  $('shiki-authorize').disabled=!info.configured;
  updateSyncDestinations();
  $('shiki-authorize').innerHTML = (info.connected ? I18n.t("Сменить аккаунт ") : I18n.t("Войти через {0} ",state.provider==='mal' ? 'MAL' : 'Shikimori')) + icon('open_in_new');
  $('watch-shiki-connect').textContent = info.connected ? I18n.t("Мой список · {0}",providerLabel(state.provider)) : I18n.t("Подключить список");
}
async function refreshShikiStatus() {
  state.shikiStatus = await api('/api/shiki/status');
  updateShikiStatusUI();
  return state.shikiStatus;
}
function showShikiDialog() {
  setProvider(state.provider);
  $('shiki-error').classList.add('hidden');
  const info = state.shikiStatus[state.provider] || {};
  if (info.error) { $('shiki-error').textContent = I18n.translate(info.error); $('shiki-error').classList.remove('hidden'); }
  $('shiki-dialog').showModal();
}
function setWatchMenu(open) {
  const show = Boolean(open);
  document.body.classList.toggle('watch-menu-open', show);
  $('sidebar-scrim').classList.toggle('hidden', !show);
  $('menu-toggle').setAttribute('aria-expanded', String(show));
  $('menu-toggle').setAttribute('aria-label', show ? I18n.t("Скрыть меню") : I18n.t("Показать меню"));
}
function updateMiniInfo() {
  $('mini-series-title').textContent = state.series?.title || I18n.t("Аниме");
  $('mini-episode-title').textContent = state.episode?.title || I18n.t("Серия");
  $('mini-toggle').innerHTML = icon(video.paused ? 'play_arrow' : 'pause');
  $('mini-toggle').setAttribute('aria-label', video.paused ? I18n.t("Воспроизвести") : I18n.t("Пауза"));
}
function enterMini() {
  if (!state.episode || !state.player?.getAssetUri() || video.ended) return false;
  closeSettings();
  $('mini-media').appendChild($('player-frame'));
  $('mini-player').classList.remove('hidden');
  state.mini = true;
  updateMiniInfo();
  updateAssPosition();
  return true;
}
function restorePlayer() {
  if (!state.mini) return;
  $('watch-player-slot').appendChild($('player-frame'));
  $('mini-player').classList.add('hidden');
  state.mini = false;
  showPlayerControls();
  updateAssPosition();
}
function showView(view) {
  if (['watch', 'season'].includes(view) && !state.series) view = 'discover';
  if (state.view === 'watch' && view !== 'watch' && !enterMini()) stopPlayback();
  if (view === 'watch') restorePlayer();
  if (view !== 'watch') closeSettings();
  state.view = view;
  setWatchMenu(false);
  $('sidebar').classList.toggle('collapsed', view !== 'watch' && state.sidebarCollapsed);
  $('menu-toggle').setAttribute('aria-expanded', String(view !== 'watch' && !mobileLayout.matches && !state.sidebarCollapsed));
  $('discover-view').classList.toggle('hidden', view !== 'discover');
  $('list-view').classList.toggle('hidden', view !== 'list');
  $('watch-view').classList.toggle('hidden', view !== 'watch');
  $('season-view').classList.toggle('hidden', view !== 'season');
  $('info-view').classList.toggle('hidden', view !== 'info');
  $('nav-discover').classList.toggle('active', view === 'discover');
  $('nav-list').classList.toggle('active', view === 'list');
  $('nav-current').classList.toggle('active', view === 'watch');
  window.scrollTo(0, 0);
  if (view === 'list') loadShikiList();
  saveRoute();
}
function openSeasonPage() {
  if (!state.series || !state.currentSeason) return;
  updateSeasonPresentation();
  renderSeasonEpisodes();
  showView('season');
  loadSeasonInformation();
}
function cardMarkup(item) {
  return I18n.html(`<button class="anime-card" type="button" data-id="${escapeHtml(item.id)}"><span class="card-image">${item.poster ? `<img src="${escapeHtml(item.poster)}" alt="" loading="lazy">` : ''}${item.age_rating ? `<span class="card-badge">${escapeHtml(ageLabel(item.age_rating))}</span>` : ''}</span><span class="card-info"><strong>${escapeHtml(item.title)}</strong><span class="card-meta">${escapeHtml(item.year || I18n.t("Год не указан"))} · ${escapeHtml(item.episodes || '—')} серий · ${escapeHtml(item.seasons || '—')} сезонов</span><span class="card-submeta">${escapeHtml((item.genres || []).slice(0, 2).join(' · '))}</span></span></button>`);
}
function searchParams() {
  const params = new URLSearchParams({ q: state.query, genre: state.genre, age: state.age, sort: state.sort,
    offset: String(state.offset), limit: String(state.pageSize) });
  const year = state.year;
  if (year) { params.set('year_min', year); params.set('year_max', year); }
  for (const [input, param] of [['year-min','year_min'],['year-max','year_max'],['episodes-min','episodes_min'],['episodes-max','episodes_max'],['seasons-min','seasons_min'],['seasons-max','seasons_max']]) {
    const value = $(input).value.trim(); if (value) params.set(param, value);
  }
  return params;
}
function filtersActive() { return Boolean(state.query || state.genre || state.age || state.year || ['year-min','year-max','episodes-min','episodes-max','seasons-min','seasons-max'].some((id) => $(id).value)); }
function renderFeatured() {
  const item = state.featuredItems[state.featuredIndex];
  if (!item) return;
  state.featured = item;
  const image = $('feature-image');
  image.onerror = () => {
    image.onerror = null;
    if (item.fallback_image && image.src !== item.fallback_image) image.src = item.fallback_image;
  };
  image.src = item.image || item.fallback_image || '';
  $('feature-title').textContent = item.title;
  $('feature-title').title = item.title;
  $('feature-meta').textContent = [item.year, item.episodes ? I18n.t("{0} серий",item.episodes) : '', (item.genres || []).slice(0, 2).join(' · ')].filter(Boolean).join('  ·  ');
  $('feature-dots').innerHTML = state.featuredItems.map((entry, index) => I18n.html(`<button type="button" data-feature-index="${index}" aria-label="Показать ${escapeHtml(entry.title)}" aria-current="${index === state.featuredIndex}"></button>`)).join('');
  $('feature-hero').classList.toggle('hidden', filtersActive());
}
async function loadFeatured() {
  try {
    const data = await api('/api/featured');
    state.featuredItems = data.items || [];
    state.featuredIndex = 0;
    renderFeatured();
    clearInterval(state.featuredTimer);
    state.featuredTimer = setInterval(() => {
      if (state.view !== 'discover' || filtersActive() || document.hidden || state.featuredItems.length < 2) return;
      state.featuredIndex = (state.featuredIndex + 1) % state.featuredItems.length;
      renderFeatured();
    }, 8500);
  } catch { /* The catalog remains usable if the live homepage is unavailable. */ }
}
async function search(append = false) {
  if (!append) state.offset = 0;
  const seq = ++state.searchSeq;
  $('catalog-grid').setAttribute('aria-busy', 'true');
  if (!append) $('catalog-grid').innerHTML = I18n.html('<div class="empty">Загружаем каталог…</div>');
  try {
    const data = await api('/api/search?' + searchParams());
    if (seq !== state.searchSeq) return;
    state.total = data.total;
    $('catalog-grid').innerHTML = (append ? $('catalog-grid').innerHTML : '') + data.items.map(cardMarkup).join('');
    $('catalog-grid').querySelectorAll('.anime-card').forEach((card) => { if (!card.dataset.bound) { card.dataset.bound = '1'; card.addEventListener('click', () => openSeries(card.dataset.id)); } });
    $('catalog-empty').classList.toggle('hidden', data.total !== 0);
    $('load-more').classList.toggle('hidden', state.offset + data.items.length >= data.total);
    $('result-total').textContent = I18n.t("{0} найдено",data.total.toLocaleString(I18n.locale));
    $('results-heading').textContent = state.query ? I18n.t("Результаты поиска") : filtersActive() ? I18n.t("Подборка") : I18n.t("Популярное");
    $('feature-hero').classList.toggle('hidden', filtersActive() || !state.featuredItems.length);
    $('filter-count').textContent = filtersActive() ? '●' : '';
  } catch (error) {
    $('catalog-grid').innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    $('load-more').classList.add('hidden');
  } finally { $('catalog-grid').removeAttribute('aria-busy'); }
}
function setGenre(genre) { state.genre = genre; $('quick-genre').value = genre; syncSiteSelect('quick-genre'); document.querySelectorAll('[data-genre]').forEach((el) => el.classList.toggle('active', el.dataset.genre === genre)); showView('discover'); search(); }
function setYear(year) { state.year = year; $('quick-year').value = year; syncSiteSelect('quick-year'); document.querySelectorAll('[data-year]').forEach((el) => el.classList.toggle('active', el.dataset.year === year)); showView('discover'); search(); }
function setAge(age) { state.age = age; $('quick-age').value = age; syncSiteSelect('quick-age'); document.querySelectorAll('[data-age]').forEach((el) => el.classList.toggle('active', el.dataset.age === age)); showView('discover'); search(); }
async function loadFilters() {
  try {
    const data = await api('/api/filters');
    $('quick-genre').innerHTML = I18n.html('<option value="">Все жанры</option>') + data.genres.map((genre) => `<option value="${escapeHtml(genre)}">${escapeHtml(genre)}</option>`).join('');
    $('sidebar-genres').innerHTML = I18n.html('<button class="sidebar-option active" data-genre="" type="button">Все жанры</button>') + data.genres.map((genre) => `<button class="sidebar-option" data-genre="${escapeHtml(genre)}" type="button">${escapeHtml(genre)}</button>`).join('');
    $('quick-year').innerHTML = I18n.html('<option value="">Любой год</option>') + Array.from({ length: data.years[1] - Math.max(1990, data.years[0]) + 1 }, (_, i) => data.years[1] - i).map((year) => `<option value="${year}">${year}</option>`).join('');
    $('sidebar-years').innerHTML = I18n.html('<button class="sidebar-option active" data-year="" type="button">Все годы</button>') + Array.from({ length: Math.min(9, Math.max(0, data.years[1] - 2016)) }, (_, i) => data.years[1] - i).map((year) => `<button class="sidebar-option" data-year="${year}" type="button">${year}</button>`).join('');
    $('quick-age').innerHTML = I18n.html('<option value="">Любой возраст</option>') + data.ratings.map((rating) => `<option value="${escapeHtml(rating)}">${escapeHtml(ageLabel(rating))}</option>`).join('');
    $('sidebar-ages').innerHTML = I18n.html('<button class="sidebar-option active" data-age="" type="button">Любой рейтинг</button>') + data.ratings.map((rating) => `<button class="sidebar-option" data-age="${escapeHtml(rating)}" type="button">${escapeHtml(ageLabel(rating))}</button>`).join('');
    for(const [id,value] of [['quick-genre',state.genre],['quick-year',state.year],['quick-age',state.age]]) {
      if(value && ![...$(id).options].some(option=>option.value===value))$(id).add(new Option(value,value));
      $(id).value=value;syncSiteSelect(id);
    }
    for(const [attribute,value] of [['genre',state.genre],['year',state.year],['age',state.age]])document.querySelectorAll(`[data-${attribute}]`).forEach(element=>element.classList.toggle('active',element.dataset[attribute]===value));
    document.querySelectorAll('[data-genre]').forEach((el) => el.addEventListener('click', () => setGenre(el.dataset.genre)));
    document.querySelectorAll('[data-year]').forEach((el) => el.addEventListener('click', () => setYear(el.dataset.year)));
    document.querySelectorAll('[data-age]').forEach((el) => el.addEventListener('click', () => setAge(el.dataset.age)));
  } catch { /* Search remains available if filter metadata is temporarily unavailable. */ }
}
function seasonTitleKey(title) {
  let key=String(title || '').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();
  key=key.replace(/([a-z])([1-9]\d*)$/, '$1 $2').replace(/\b(\d+)(?:st|nd|rd|th) season\b/g,'season $1');
  if(!/\b(?:season|part) \d+$/.test(key))key=key.replace(/\s+([2-9]\d*)$/, ' season $1');
  return key.replace(/\s+season 1$/,'');
}
function preferredSeasonId(englishTitle, seasons, shikiId = 0, baseMalId = 0) {
  const key = seasonTitleKey(englishTitle);
  if (!key) return shikiId && baseMalId && shikiId !== baseMalId ? null : seasons[0]?.id;
  const exact = seasons.filter((season) => seasonTitleKey(season.title) === key);
  if (exact.length === 1) return exact[0].id;
  if (key.includes('final season')) return seasons.find((season) => /final\s+season/i.test(season.title || ''))?.id || null;
  if (/\b(?:oad|ova)\b/.test(key)) return seasons.find((season) => /\b(?:oad|ova)\b/i.test(season.title || ''))?.id || null;
  const number = key.match(/(?:season\s*(\d+)|(\d+)(?:st|nd|rd|th)\s*season|\s([2-9])$)/)?.slice(1).find(Boolean);
  if (number) return seasons.find((season) => Number(season.season_number) === Number(number))?.id || null;
  if (shikiId) return null;
  return seasons[0]?.id;
}
async function openSeries(id, shikiId = 0, shikiTitle = '', restore = {}) {
  try { state.series = await api('/api/series/' + encodeURIComponent(id)); }
  catch (error) { alert(error.message); return; }
  await stopPlayback();
  state.episode = null; state.episodes = []; state.seasons = []; state.currentSeason = null;
  state.shikiTarget = 0; state.currentRate = null;
  state.forcedShikiId = shikiId; state.forcedShikiTitle = shikiTitle;
  state.seasonMatch = null; state.seasonRatingId = 0;
  state.seasonInfo=null;++state.seasonInfoSeq;
  state.crunchyRating = null;
  $('shiki-controls').classList.add('hidden');
  $('shiki-target').innerHTML = I18n.html('<option value="">Выберите аниме для этого сезона</option>');
  syncSiteSelect('shiki-target');
  showView('watch');
  setWatchSideTab('episodes');
  loadSimilar(id);
  const s = state.series;
  updateSeasonPresentation();
  $('series-description').textContent = s.description || I18n.t("Описание пока недоступно.");
  $('official-series-link').href = `https://www.crunchyroll.com/series/${encodeURIComponent(s.id)}`;
  setPoster($('cover-image'), s.wide || s.poster || '', s.poster || '');
  $('cover-title').textContent = s.title;
  $('cover-subtitle').textContent = I18n.t("Выберите серию в списке справа.");
  $('cover-subtitle').classList.remove('episode-label');
  $('cover-play').classList.add('hidden'); $('player-cover').classList.remove('hidden'); clearPlayerMessage();
  $('player-loading').classList.add('hidden');
  $('episode-list').innerHTML = I18n.html('<div class="episodes-status">Загружаем серии…</div>');
  $('season-select').innerHTML = I18n.html('<option>Загрузка сезонов…</option>');
  refreshRatings();
  refreshCrunchyRating(id);
  try {
    const data = await api(`/api/series/${encodeURIComponent(id)}/seasons`);
    if (state.series?.id !== id) return;
    state.seasons = data.data || [];
    $('season-select').innerHTML = state.seasons.map((season, i) => `<option value="${escapeHtml(season.id)}">${escapeHtml(seasonLabel(season, i))}</option>`).join('');
    if (state.seasons.length) {
      const restoredSeason = state.seasons.find((season) => season.id === restore.seasonId)?.id;
      const chosen = restoredSeason || preferredSeasonId(state.forcedShikiTitle, state.seasons, state.forcedShikiId, s.mal_id);
      if (chosen) {
        $('season-select').value = chosen; syncSiteSelect('season-select'); await loadSeason(chosen);
        if (restore.episodeId && state.episodes.some((ep) => ep.id === restore.episodeId)) await selectEpisode(restore.episodeId, restore.resumeTime || 0);
        if (restore.view === 'season') openSeasonPage();
      }
      else {
        $('season-select').insertAdjacentHTML('afterbegin', I18n.html('<option value="">Выберите доступный сезон</option>'));
        $('season-select').value = '';
        syncSiteSelect('season-select');
        $('episode-count').textContent = '—';
        $('episode-list').innerHTML = I18n.html('<div class="episodes-status">Выбранного сезона Shikimori нет среди доступных сезонов Crunchyroll. Можно выбрать другой сезон выше.</div>');
        await renderShikiControls();
      }
    }
    else {
      $('season-select').innerHTML = I18n.html('<option value="">Сезоны недоступны</option>');
      $('episode-count').textContent = '—';
      const region = data.availability_status === 'unavailable' && data.media_count > 0;
      $('episode-list').innerHTML = region
        ? I18n.html('<div class="episodes-status">API Crunchyroll сообщает, что серии недоступны для подключения локального плеера. Официальный сайт может получать другой ответ. <a href="') + escapeHtml($('official-series-link').href) + I18n.html('" target="_blank" rel="noopener noreferrer">Открыть на Crunchyroll ↗</a></div>')
        : I18n.html('<div class="episodes-status">Для этого сериала сейчас нет доступных серий.</div>');
      await renderShikiControls();
    }
  } catch (error) {
    $('season-select').innerHTML = I18n.html('<option value="">Сезоны недоступны</option>');
    $('episode-count').textContent = '—';
    syncSiteSelect('season-select');
    $('episode-list').innerHTML = I18n.html(`<div class="episodes-status error">${escapeHtml(error.message)}<br><a href="${$('official-series-link').href}" target="_blank" rel="noopener noreferrer">Открыть на Crunchyroll ↗</a></div>`);
    await renderShikiControls();
  }
}
async function loadSeason(id) {
  if (state.episode) await stopPlayback();
  state.currentSeason = id;
  state.seasonInfo=null;++state.seasonInfoSeq;
  state.episode = null;
  state.shikiTarget = 0;
  state.episodes = [];
  state.seasonMatch = null; state.seasonRatingId = 0;
  saveRoute();
  refreshRatings();
  updateSeasonPresentation();
  $('player-cover').classList.remove('hidden');
  setPoster($('cover-image'), state.series?.wide || state.series?.poster || '', state.series?.poster || '');
  $('cover-title').textContent = state.series?.title || I18n.t("Аниме");
  $('cover-subtitle').textContent = I18n.t("Выберите серию в списке справа.");
  $('cover-subtitle').classList.remove('episode-label');
  $('cover-play').classList.add('hidden');
  updateNextEpisode();
  $('episode-list').innerHTML = I18n.html('<div class="episodes-status">Загружаем серии…</div>');
  try {
    const data = await api(`/api/seasons/${encodeURIComponent(id)}/episodes`);
    if (state.currentSeason !== id) return;
    state.episodes = data.data || [];
    updateSeasonPresentation();
    renderSeasonEpisodes();
    $('episode-count').textContent = I18n.t("{0} серий",state.episodes.length);
    $('episode-list').innerHTML = state.episodes.map((ep, index) => {
      const meta = ep.episode_metadata || {};
      const image = ep.images?.thumbnail?.[0]?.at(-1)?.source || ep.images?.poster_wide?.[0]?.at(-1)?.source || '';
      return I18n.html(`<button class="episode-card" type="button" data-id="${escapeHtml(ep.id)}"><span class="ep-thumb">${image ? `<img src="${escapeHtml(image)}" alt="" loading="lazy">` : `<span class="ep-placeholder">${icon('play_arrow')}</span>`}<span class="ep-play">${icon('play_arrow')}</span></span><span class="ep-copy"><strong>${escapeHtml(ep.title || I18n.t("Серия {0}",index + 1))}</strong><span class="ep-index">Серия ${escapeHtml(meta.episode || meta.episode_number || index + 1)}</span><span>${escapeHtml(currentSeasonTitle())}</span></span></button>`);
    }).join('') || I18n.html('<div class="episodes-status">Серии не найдены.</div>');
    $('episode-list').querySelectorAll('.episode-card').forEach((card) => card.addEventListener('click', () => selectEpisode(card.dataset.id)));
    updateNextEpisode();
    await resolveSeasonMatch(id);
    renderShikiControls();
  } catch (error) { $('episode-count').textContent = '—'; $('episode-list').innerHTML = `<div class="episodes-status error">${escapeHtml(error.message)}</div>`; await renderShikiControls(); }
}
async function resolveSeasonMatch(id) {
  const season = state.seasons.find((item) => item.id === id);
  if (!season) return;
  const seasonTitle = season.title || '';
  const searchTitle = /^(?:season|сезон)\s*\d+$/i.test(seasonTitle.trim()) ? `${state.series.title} ${seasonTitle}` : seasonTitle || state.series.title;
  const provider=state.provider;
  const params = new URLSearchParams({ provider, title: searchTitle,
    episodes: String(state.episodes.length), mal_id: String(state.series.mal_id || 0) });
  try {
    const result = await api('/api/shiki/season?' + params);
    if (state.currentSeason !== id) return;
    if(state.provider !== provider)return;
    state.seasonMatch = result;
    const savedId = Number(localStorage.getItem(seasonMapKey(state.provider, state.series.id, id))) || 0;
    const validId = value => result.items.some((item) => item.mal_id === value && item.score >= 100);
    const forcedId = validId(state.forcedShikiId) ? state.forcedShikiId : 0;
    const preferredId = (validId(savedId) ? savedId : 0) || forcedId || result.matched_id;
    const preferred = result.items.find((item) => item.mal_id === preferredId);
    if (preferred?.poster) setPoster($('cover-image'), preferred.poster, state.series?.poster || state.series?.wide || '');
    state.seasonRatingId = preferredId || 0;
    saveRoute();
    updateSeasonPresentation();
    refreshRatings();
    if(state.view==='season')loadSeasonInformation();
  } catch { /* Manual Shikimori selection remains available. */ }
}
function setWatchSideTab(tab) {
  const episodes = tab !== 'similar';
  $('episodes-tab').classList.toggle('active', episodes);
  $('similar-tab').classList.toggle('active', !episodes);
  $('episodes-tab').setAttribute('aria-selected', String(episodes));
  $('similar-tab').setAttribute('aria-selected', String(!episodes));
  $('episodes-content').classList.toggle('hidden', !episodes);
  $('similar-content').classList.toggle('hidden', episodes);
}
async function loadSimilar(id) {
  const seq = ++state.relatedSeq;
  $('similar-list').innerHTML = I18n.html('<div class="episodes-status">Подбираем похожие аниме…</div>');
  try {
    const data = await api('/api/related/' + encodeURIComponent(id));
    if (seq !== state.relatedSeq || state.series?.id !== id) return;
    $('similar-list').innerHTML = data.items.map((item) => I18n.html(`<button class="similar-card" type="button" data-id="${escapeHtml(item.id)}"><span class="similar-thumb">${item.wide || item.poster ? `<img src="${escapeHtml(item.wide || item.poster)}" alt="" loading="lazy">` : ''}${item.episodes ? I18n.html(`<span class="similar-badge">${escapeHtml(item.episodes)} серий</span>`) : ''}</span><span class="similar-copy"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml((item.genres || []).slice(0, 2).join(' · '))}</span><span class="similar-meta">${escapeHtml(item.year || I18n.t("Год не указан"))} · ${escapeHtml(item.seasons || '—')} сезонов</span></span></button>`)).join('') || I18n.html('<div class="episodes-status">Похожих аниме пока нет.</div>');
    $('similar-list').querySelectorAll('.similar-card').forEach((card) => card.addEventListener('click', () => openSeries(card.dataset.id)));
  } catch (error) {
    if (seq === state.relatedSeq) $('similar-list').innerHTML = `<div class="episodes-status error">${escapeHtml(error.message)}</div>`;
  }
}
function updateNextEpisode() {
  const index = state.episodes.findIndex((item) => item.id === state.episode?.id);
  const available = index >= 0 && index < state.episodes.length - 1;
  $('next-episode').disabled = !available;
  $('next-episode').title = available ? state.episodes[index + 1].title || I18n.t("Следующая серия") : I18n.t("Следующей серии нет");
}
async function refreshRatings() {
  const seq = ++state.ratingsSeq;
  const s = state.series;
  const malId = seasonInformationId();
  $('community-ratings').innerHTML = `<a id="crunchy-rating" class="rating-link" href="${escapeHtml($('official-series-link').href)}" target="_blank" rel="noopener noreferrer">Crunchyroll <strong>${state.crunchyRating == null ? '—' : escapeHtml(state.crunchyRating.toFixed(1)) + ' / 5'}</strong></a><span id="other-ratings">${malId ? I18n.t("Загружаем оценки…") : I18n.t("Оценки MAL и Shikimori недоступны")}</span>`;
  if (!malId) return;
  try {
    const data = await api(`/api/ratings?mal_id=${malId}&provider=${state.provider}`);
    if (seq !== state.ratingsSeq || state.series?.id !== s.id || seasonInformationId() !== malId) return;
    const malSource = data.mal_source === 'MyAnimeList' ? 'MyAnimeList' : data.mal_source === 'Shikimori' ? I18n.t("Оценка MAL через Shikimori") : I18n.t("Оценка MAL через Jikan");
    $('other-ratings').outerHTML = `<a class="rating-link" href="${escapeHtml(data.mal_url)}" target="_blank" rel="noopener noreferrer" title="${malSource}">MAL <strong>${data.mal == null ? '—' : escapeHtml(data.mal.toFixed(2))}</strong></a><a class="rating-link" href="${escapeHtml(data.shikimori_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(I18n.t('Средняя оценка пользователей Shikimori'))}">Shikimori <strong>${data.shikimori == null ? '—' : escapeHtml(data.shikimori.toFixed(2))}</strong></a>`;
  } catch { if (seq === state.ratingsSeq && $('other-ratings')) $('other-ratings').textContent = I18n.t("Оценки MAL и Shikimori сейчас недоступны"); }
}
async function refreshCrunchyRating(id) {
  try {
    const data = await api(`/api/series/${encodeURIComponent(id)}/rating`);
    if (state.series?.id !== id) return;
    state.crunchyRating = data.rating;
    const value = $('crunchy-rating')?.querySelector('strong');
    if (value) value.textContent = data.rating == null ? '—' : `${data.rating.toFixed(1)} / 5`;
  } catch { /* The other ratings remain available. */ }
}
const shikiListPending = new Map();
async function fetchShikiItems(provider, force = false) {
  if (!force && state.shikiItems[provider]) return state.shikiItems[provider];
  if(shikiListPending.has(provider))return shikiListPending.get(provider);
  const pending=api(`/api/shiki/list?provider=${provider}${force ? '&refresh=1' : ''}`)
    .then(data => {state.shikiItems[provider]=data;return data;})
    .finally(() => shikiListPending.delete(provider));
  shikiListPending.set(provider,pending);
  return pending;
}
function drainShikiScores() {
  while (state.scoreLoading < 3 && state.scoreQueue.length) {
    const { card, provider, malId } = state.scoreQueue.shift();
    if (!card.isConnected) continue;
    state.scoreLoading++;
    const key = `io-user-mean:${malId}`;
    api(`/api/shiki/score?provider=one&mal_id=${malId}`).then((result) => {
      state.scoreCache.set(key, result.score);
      if (card.isConnected) card.querySelector('.list-shiki-score').textContent = result.score == null ? '—' : String(result.score);
    }).catch(() => {
      if (card.isConnected) card.querySelector('.list-shiki-score').textContent = '—';
    }).finally(() => { state.scoreLoading--; drainShikiScores(); });
  }
}
function observeShikiScores(provider) {
  state.listScoreObserver?.disconnect();
  state.scoreQueue.length = 0;
  if (provider === 'mal') return;
  state.listScoreObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const card = entry.target;
      state.listScoreObserver.unobserve(card);
      const malId = Number(card.dataset.mal);
      const key = `io-user-mean:${malId}`;
      if (state.scoreCache.has(key)) {
        const score = state.scoreCache.get(key);
        card.querySelector('.list-shiki-score').textContent = score == null ? '—' : String(score);
      } else if (malId) state.scoreQueue.push({ card, provider, malId });
    }
    drainShikiScores();
  }, { rootMargin: '250px' });
  $('list-grid').querySelectorAll('.list-card').forEach((card) => state.listScoreObserver.observe(card));
}
async function loadShikiList(force = false) {
  const provider = state.provider;
  const connected = Boolean(state.shikiStatus[provider]?.connected);
  $('list-unconnected').classList.toggle('hidden', connected);
  $('list-content').classList.toggle('hidden', !connected);
  $('list-message').classList.toggle('hidden', !connected);
  if (!connected) { $('list-count').textContent = ''; return; }
  $('list-message').textContent = I18n.t("Загружаем ваш список…");
  try {
    const data = await fetchShikiItems(provider, force);
    if (provider !== state.provider) return;
    $('list-count').textContent = I18n.t("{0} в списке · {1} доступны в каталоге",data.total,data.available);
    const items = data.items.filter((item) => !state.listFilter || item.rate.status === state.listFilter);
    $('list-grid').innerHTML = items.map((item) => {
      const current = item.rate.episodes || 0;
      const total = item.total_episodes || 0;
      const progress = total ? Math.min(100, Math.round(current / total * 100)) : 0;
      const communityRating = provider === 'mal'
        ? `MAL: <span class="list-mal-score">${Number.isFinite(item.mal_score) ? escapeHtml(item.mal_score.toFixed(2)) : '—'}</span>`
        : `${I18n.language === 'en' ? 'Shikimori' : 'Шики'}: <span class="list-shiki-score" title="${escapeHtml(I18n.t('Средняя оценка пользователей Shikimori'))}">…</span>`;
      const content = I18n.html(`<span class="card-image">${item.poster ? `<img src="${escapeHtml(item.poster)}" data-fallback="${escapeHtml(item.poster_fallback || '')}" data-fallback2="${escapeHtml(item.catalog_poster || '')}" alt="" loading="lazy">` : ''}${item.crunchy_id ? '' : I18n.html('<span class="card-badge">Нет в каталоге</span>')}</span><span class="card-info"><strong>${escapeHtml(item.title)}</strong><span class="card-meta">${escapeHtml(statusLabel(item.rate.status))} · ${escapeHtml(current)}${total ? ` / ${escapeHtml(total)}` : ''} серий</span><span class="card-submeta">${escapeHtml(I18n.t('Моя оценка: {0}', item.rate.score || '—'))} · ${communityRating}</span><span class="progress"><span style="width:${progress}%"></span></span></span>`);
      return item.crunchy_id ? `<button class="anime-card list-card" type="button" data-id="${escapeHtml(item.crunchy_id)}" data-season="${escapeHtml(item.season_id || '')}" data-mal="${item.mal_id}" data-english="${escapeHtml(item.english_title || '')}">${content}</button>` : `<a class="anime-card list-card unavailable" data-mal="${item.mal_id}" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`;
    }).join('');
    $('list-empty').classList.toggle('hidden', items.length > 0);
    $('list-grid').querySelectorAll('button.list-card').forEach((card) => card.addEventListener('click', () => openSeries(card.dataset.id, Number(card.dataset.mal), card.dataset.english, {seasonId:card.dataset.season})));
    observeShikiScores(provider);
    $('list-message').classList.add('hidden');
  } catch (error) { $('list-message').textContent = error.message; }
}
async function renderShikiControls() {
  const renderSeq = ++state.shikiRenderSeq;
  const series = state.series;
  if (!series || state.view !== 'watch') return;
  const provider = state.provider;
  const connected = Boolean(state.shikiStatus[provider]?.connected);
  $('shiki-controls').classList.toggle('hidden', !connected);
  if (!connected) return;
  shikiMessage(I18n.t("Загружаем список…"));
  let items = [];
  try { items = (await fetchShikiItems(provider)).items; }
  catch (error) { shikiMessage(error.message, true); return; }
  if (renderSeq !== state.shikiRenderSeq || state.series?.id !== series.id || state.provider !== provider) return;
  const season = state.seasons.find((item) => item.id === state.currentSeason);
  const savedId = state.currentSeason ? Number(localStorage.getItem(seasonMapKey(provider, series.id, state.currentSeason))) || 0 : 0;
  const validId = value => state.seasonMatch?.items.some((item) => item.mal_id === value && item.score >= 100);
  const forcedId = validId(state.forcedShikiId) ? state.forcedShikiId : 0;
  const defaultId = (validId(savedId) ? savedId : 0) || forcedId || state.seasonMatch?.matched_id || 0;
  let options = I18n.html('<option value="">Выберите аниме для этого сезона</option>');
  const added = new Set();
  for (const candidate of state.seasonMatch?.items || []) {
    if (candidate.score < 100 || added.has(candidate.mal_id)) continue;
    added.add(candidate.mal_id);
    const inList = items.some((item) => item.mal_id === candidate.mal_id);
    options += `<option value="${candidate.mal_id}">${escapeHtml(candidate.title || candidate.english_title)}${inList ? I18n.t(" · в моём списке") : I18n.t(" · добавить в список")}</option>`;
  }
  if (series.mal_id && !added.has(series.mal_id) && !items.some((item) => item.mal_id === series.mal_id)) {
    added.add(series.mal_id);
    options += I18n.html(`<option value="${series.mal_id}">${escapeHtml(series.title)} · добавить в список</option>`);
  }
  options += items.filter((item) => !added.has(item.mal_id)).map((item) => `<option value="${item.mal_id}">${escapeHtml(item.title)}</option>`).join('');
  $('shiki-target').innerHTML = options;
  $('shiki-target').value = defaultId && [...$('shiki-target').options].some((option) => option.value === String(defaultId)) ? String(defaultId) : '';
  syncSiteSelect('shiki-target');
  state.shikiTarget = Number($('shiki-target').value) || 0;
  state.forcedShikiId = 0;
  if (!state.shikiTarget) shikiMessage(I18n.t("Не удалось однозначно сопоставить сезон. Найдите нужную запись в списке."));
  else shikiMessage(state.seasonMatch?.matched_id === state.shikiTarget ? I18n.t("Запись для текущего сезона найдена.") : '');
  state.seasonRatingId = state.shikiTarget || 0;
  saveRoute();
  updateSeasonPresentation();
  refreshRatings();
  await loadCurrentRate();
}
async function loadCurrentRate() {
  const id = state.shikiTarget;
  if (!id || !state.shikiStatus[state.provider]?.connected) { state.currentRate = null; $('shiki-episodes').value = '0'; $('shiki-score').value = '0'; $('shiki-rate-status').value = 'planned'; syncSiteSelect('shiki-score'); syncSiteSelect('shiki-rate-status'); return; }
  try {
    const rate = await api(`/api/shiki/rate?provider=${state.provider}&mal_id=${id}`);
    if (state.shikiTarget !== id) return;
    state.currentRate = rate;
    $('shiki-episodes').value = String(rate?.episodes || 0);
    $('shiki-score').value = String(rate?.score || 0);
    $('shiki-rate-status').value = rate?.status || 'planned';
    syncSiteSelect('shiki-score'); syncSiteSelect('shiki-rate-status');
  } catch (error) { shikiMessage(error.message, true); }
}
function updateSyncDestinations() {
  let saved=null;try { const value=JSON.parse(localStorage.getItem('crunchy-sync-providers'));if(Array.isArray(value))saved=value; } catch {}
  document.querySelectorAll('[data-sync-provider]').forEach(input=>{
    const provider=input.dataset.syncProvider;
    input.disabled=!state.shikiStatus[provider]?.connected;
    input.checked=!input.disabled && (saved ? saved.includes(provider) : provider===state.provider);
  });
}
function syncDestinations() {
  return [...document.querySelectorAll('[data-sync-provider]:checked')].filter(input=>!input.disabled).map(input=>input.dataset.syncProvider);
}
document.querySelectorAll('[data-sync-provider]').forEach(input=>input.addEventListener('change',()=>{
  localStorage.setItem('crunchy-sync-providers',JSON.stringify(syncDestinations()));
  state.watchedKey='';
}));
async function saveShikiRate(fields, automatic=false) {
  if (!state.shikiTarget) { shikiMessage(I18n.t("Сначала выберите запись для сезона."), true); return null; }
  const providers=syncDestinations();
  if(!providers.length){ shikiMessage(I18n.t("Выберите сервисы синхронизации."),true);return null; }
  const id=state.shikiTarget, source=state.provider;
  try {
    shikiMessage(I18n.t("Синхронизируем…"));
    const data=await api('/api/lists/rate',{method:'POST',body:{providers,mal_id:id,...fields,automatic}});
    for(const provider of Object.keys(data.results))state.shikiItems[provider]=null;
    const failures=Object.entries(data.errors).map(([provider,error])=>providerLabel(provider)+': '+I18n.translate(error));
    const success=Object.keys(data.results).map(providerLabel).join(', ');
    if(state.shikiTarget!==id || state.provider!==source)return null;
    const rate=data.results[source];
    if(rate){
      state.currentRate=rate;
      $('shiki-episodes').value=String(rate.episodes||0);
      $('shiki-score').value=String(rate.score||0);
      $('shiki-rate-status').value=rate.status||'planned';
      syncSiteSelect('shiki-score');syncSiteSelect('shiki-rate-status');
    }
    shikiMessage([success ? I18n.t("Сохранено: {0} ✓",success) : '',...failures].filter(Boolean).join(' · '),failures.length>0);
    return failures.length ? null : (rate || Object.values(data.results)[0]);
  } catch(error){shikiMessage(error.message,true);return null;}
}
function episodeNumber() {
  const meta = state.episode?.episode_metadata || {};
  const raw = meta.episode || meta.episode_number;
  if (Number.isInteger(Number(raw)) && Number(raw) > 0) return Number(raw);
  const index = state.episodes.findIndex((item) => item.id === state.episode?.id);
  return index >= 0 ? index + 1 : 0;
}
async function markWatched(auto = false) {
  if (!state.shikiStatus[state.provider]?.connected || !state.shikiTarget || !state.episode) {
    if (!auto) shikiMessage(I18n.t("Выберите серию и запись для сезона."), true);
    return;
  }
  const count = episodeNumber();
  if (!count) { shikiMessage(I18n.t("Не удалось определить номер серии."), true); return; }
  const key = `${syncDestinations().join(',')}:${state.shikiTarget}:${state.episode.id}`;
  if (auto && state.watchedKey === key) return;
  const watched = Math.max(count, Number(state.currentRate?.episodes || 0));
  const nextStatus = state.currentRate?.status === 'planned' ? 'watching' : (state.currentRate?.status || 'watching');
  const rate = await saveShikiRate({ episodes: watched, status: nextStatus }, true);
  if (rate) state.watchedKey = key;
}
async function createPlayer() {
  if (state.player) return state.player;
  if (!window.isSecureContext) throw new Error(I18n.t("Защищённое видео не работает по HTTP-адресу локальной сети. На Windows откройте плеер через SSH-туннель по адресу http://127.0.0.1:8765."));
  state.fairPlay = typeof window.WebKitMediaKeys === 'function' && window.WebKitMediaKeys.isTypeSupported('com.apple.fps.1_0', 'video/mp4');
  if (state.fairPlay && window.shaka) FairPlaySupport.install(window, shaka);
  if (typeof navigator.requestMediaKeySystemAccess !== 'function') throw new Error(I18n.t("В этом браузере недоступен DRM. Откройте плеер в Chrome или Firefox с включённым Widevine."));
  if (!window.shaka || !shaka.Player.isBrowserSupported()) throw new Error(I18n.t("Этот браузер не поддерживает защищённое видео. Попробуйте Chrome или Firefox с включённым DRM."));
  state.player = new shaka.Player();
  await state.player.attach(video);
  state.player.configure({
    drm: state.fairPlay ? {
      servers: {'com.apple.fps.1_0': `${location.origin}/api/license/fairplay`},
      advanced: {
        'com.apple.fps.1_0': {serverCertificateUri: `${location.origin}/fairplay-certificate.der`},
        'com.apple.fps': {serverCertificateUri: `${location.origin}/fairplay-certificate.der`}
      },
      initDataTransform: (data, type, info) => type === 'skd'
        ? shaka.drm.FairPlay.initDataTransform(data, FairPlaySupport.contentId(shaka.util.StringUtils.fromBytesAutoDetect(data)), info.serverCertificate) : data
    } : {servers: {'com.widevine.alpha': `${location.origin}/api/license`}},
    streaming: {bufferingGoal: 30, ...(state.fairPlay ? {useNativeHlsForFairPlay: true, preferNativeHls: true} : {})},
    textDisplayer: { fontScaleFactor: state.subtitleScale },
    textDisplayFactory: () => state.fairPlay ? new shaka.text.NativeTextDisplayer(video) : new shaka.text.UITextDisplayer(video, $('player-frame'))
  });
  state.player.getNetworkingEngine().registerRequestFilter((type, request) => {
    if (type === shaka.net.NetworkingEngine.RequestType.LICENSE) {
      request.headers['X-Local-Player'] = '1';
      if (state.fairPlay) {
        const spc = shaka.util.Uint8ArrayUtils.toStandardBase64(new Uint8Array(request.body));
        request.body = shaka.util.StringUtils.toUTF8('spc=' + encodeURIComponent(spc));
        request.headers['Content-Type'] = 'application/octet-stream';
      }
    } else if (request.uris?.[0]?.startsWith(location.origin + '/')) {
      if (request.uris[0].includes('/api/')) request.headers['X-Local-Player'] = '1';
    } else if (request.uris?.[0]?.startsWith('https://')) { request.uris = request.uris.map((uri) => `${location.origin}/api/media?url=${encodeURIComponent(uri)}`); request.headers['X-Local-Player'] = '1'; }
  });
  state.player.getNetworkingEngine().registerResponseFilter((type, response) => {
    if (type === shaka.net.NetworkingEngine.RequestType.LICENSE && state.fairPlay) {
      let ckc = shaka.util.StringUtils.fromUTF8(response.data).trim();
      if (ckc.startsWith('<ckc>')) ckc = ckc.slice(5, -6).trim();
      response.data = shaka.util.Uint8ArrayUtils.fromBase64(ckc).buffer;
    }
    if (type === shaka.net.NetworkingEngine.RequestType.MANIFEST && response.uri?.includes('/api/media?url=')) response.uri = new URL(response.uri).searchParams.get('url');
  });
  state.player.addEventListener('error', (event) => {
    if (event.detail?.severity === shaka.util.Error.Severity.RECOVERABLE) return;
    const timeAtError = video.currentTime;
    if ([1001, 1002, 1003].includes(event.detail?.code) && state.episode && !state.recoveringPlayback && state.playbackRecoveryAttempts < 2) {
      state.recoveringPlayback = true;
      state.playbackRecoveryAttempts++;
      state.recoveryTime = timeAtError;
      playerMessage(I18n.t("Восстанавливаем соединение и обновляем видео…"));
      (async () => {
        let online = false;
        const deadline = Date.now() + 180000;
        do {
          await new Promise((resolve) => setTimeout(resolve, 4000));
          try {
            const response = await fetch('/api/status', { headers: { 'X-Local-Player': '1' }, signal: AbortSignal.timeout(6000) });
            online = response.ok;
          } catch { /* Wi-Fi may still be reconnecting. */ }
        } while (!online && Date.now() < deadline);
        if (!online) { state.recoveringPlayback = false; playerMessage(I18n.t("Не удалось восстановить связь с сервером. Проверьте Wi-Fi ноутбука.")); return; }
        const episodeId = state.episode?.id;
        if (episodeId) await startPlayback(episodeId, Math.max(0, timeAtError - 2));
        state.recoveringPlayback = false;
      })();
      return;
    }
    clearTimeout(state.playbackErrorTimer);
    state.playbackErrorTimer = setTimeout(() => {
      if (video.currentTime > timeAtError + 0.2) return;
      playerMessage(event.detail?.code === 6020
        ? I18n.t("Браузеру недоступен DRM. Если вы открыли плеер с другого ПК, подключитесь через SSH-туннель и откройте http://127.0.0.1:8765.")
        : I18n.t("Видео остановилось (код {0}). Попробуйте выбрать серию ещё раз.",event.detail?.code || I18n.t("неизвестен")));
    }, 3500);
  });
  state.player.addEventListener('trackschanged', updateQualities);
  state.player.addEventListener('variantchanged', updateQualities);
  state.player.addEventListener('textchanged', updateSubtitles);
  return state.player;
}
function audioVersions(episode) {
  const seen = new Set();
  const versions = (episode?.versions || []).filter((version) => version.guid && version.audio_locale);
  if (!versions.length && episode?.id) versions.push({ guid: episode.id, audio_locale: episode.audio_locale || 'ja-JP', original: true });
  return versions.filter((version) => { if (seen.has(version.audio_locale)) return false; seen.add(version.audio_locale); return true; });
}
function audioLabel(locale) {
  try { const name = new Intl.DisplayNames([I18n.language], { type: 'language' }).of(locale); return name.charAt(0).toUpperCase() + name.slice(1); }
  catch { return locale; }
}
function setupAudioOptions(episode) {
  const versions = audioVersions(episode);
  const preferred = localStorage.getItem('crunchy-audio-locale');
  const selected = versions.find((version) => version.audio_locale === preferred) || versions.find((version) => version.guid === episode.id) || versions.find((version) => version.original) || versions[0];
  state.audioLocale = selected?.audio_locale || '';
  $('audio').innerHTML = versions.map((version) => `<option value="${escapeHtml(version.audio_locale)}">${escapeHtml(audioLabel(version.audio_locale))}${version.original ? I18n.t(" · оригинал") : ''}</option>`).join('');
  $('audio').value = state.audioLocale;
  $('audio-setting-row').classList.toggle('hidden', versions.length < 2);
  updateSettingsSummary();
}
function selectedStreamId(episode) {
  return audioVersions(episode).find((version) => version.audio_locale === state.audioLocale)?.guid || episode.id;
}
async function selectEpisode(id, resumeTime = 0) {
  state.playbackRecoveryAttempts = 0;
  state.recoveringPlayback = false;
  state.episode = state.episodes.find((ep) => ep.id === id);
  if (!state.episode) return;
  updateSeasonPresentation();
  saveRoute();
  rememberEpisode(resumeTime);
  state.watchedKey = '';
  setupAudioOptions(state.episode);
  updateMiniInfo();
  updateNextEpisode();
  $('episode-list').querySelectorAll('.episode-card').forEach((card) => card.classList.toggle('selected', card.dataset.id === id));
  $('cover-title').textContent = state.episode.title || I18n.t("Серия");
  $('cover-subtitle').textContent = I18n.t("Серия {0}",episodeNumber());
  $('cover-subtitle').classList.add('episode-label');
  setPoster($('cover-image'), state.episode.images?.thumbnail?.[0]?.at(-1)?.source || state.series?.wide || state.series?.poster || '', state.series?.poster || '');
  $('cover-play').classList.remove('hidden'); $('player-cover').classList.remove('hidden'); clearPlayerMessage();
  if (!state.connected) { $('account-dialog').showModal(); return; }
  await startPlayback(id, resumeTime);
}
function clearSubtitleBlobUrls() {
  for (const uri of state.subtitleBlobUrls || []) URL.revokeObjectURL(uri);
  state.subtitleBlobUrls = [];
}
async function addPlaybackSubtitles(player, subtitles) {
  for (const [language, subtitle] of Object.entries(subtitles || {})) {
      try {
        const before = new Set(player.getTextTracks().map((track) => String(track.id)));
        let uri = `${location.origin}/api/subtitle?lang=${encodeURIComponent(language)}`;
        if (state.fairPlay) {
          const response = await fetch(uri, {headers: {'X-Local-Player': '1'}});
          if (!response.ok) throw new Error('Subtitle download failed.');
          uri = URL.createObjectURL(new Blob([await response.text()], {type: 'text/vtt'}));
          (state.subtitleBlobUrls ||= []).push(uri);
        }
        await player.addTextTrackAsync(uri, subtitle.language || language, 'subtitles', 'text/vtt');
        const track = player.getTextTracks().find((item) => !before.has(String(item.id)));
        if (track && String(subtitle.format || '').toLowerCase() !== 'vtt') state.assTracks.set(String(track.id), language);
      }
      catch { /* Missing subtitles must not stop playback. */ }
    }
}
async function changeFairPlayQuality(height) {
  if (state.fairPlayQualitySwitching || state.audioSwitching) { updateQualities(); return; }
  if (!state.fairPlayPlayback || height === state.fairPlayQuality) return;
  const previous = state.fairPlayQuality;
  const position = video.currentTime;
  const paused = video.paused;
  const language = state.player.getTextTracks().find(track => String(track.id) === state.assTrackId || track.active)?.language;
  state.fairPlayQualitySwitching = true;
  state.fairPlayQuality = height;
  closeSettings();
  $('player-loading').classList.remove('hidden');
  async function reload(quality) {
    clearAssRenderer();
    state.assTracks.clear();
    await state.player.unload();
    clearSubtitleBlobUrls();
    await state.player.load(FairPlaySupport.qualityUrl(state.fairPlayPlayback.url, quality), position, 'application/x-mpegurl');
    await addPlaybackSubtitles(state.player, state.fairPlayPlayback.subtitles);
    const subtitle = SubtitlePreference.choose(state.player.getTextTracks(), SubtitlePreference.read(localStorage) ?? language);
    if (subtitle !== null) await selectSubtitle(subtitle);
    video.playbackRate = Number($('speed').value);
    if (!paused) await video.play();
  }
  try { await reload(height); }
  catch (error) {
    state.fairPlayQuality = previous;
    await reload(previous).catch(() => {});
    playerMessage(error.message || I18n.t("Не удалось воспроизвести серию."));
  } finally {
    state.fairPlayQualitySwitching = false;
    $('player-loading').classList.add('hidden');
    updateQualities(); updateSubtitles();
  }
}
async function startPlayback(id, resumeTime = 0) {
  let streamOpened = false;
  clearPlayerMessage();
  state.lastMediaTime = 0;
  closeSettings();
  $('cover-play').classList.add('hidden');
  $('player-loading').classList.remove('hidden');
  try {
    const player = await createPlayer();
    const previousSubtitleLocale = state.assTrackId
      ? player.getTextTracks().find((track) => String(track.id) === state.assTrackId)?.language
      : player.isTextTrackVisible() ? player.getTextTracks().find((track) => track.active)?.language : '';
    const previousQuality = $('quality').value;
    clearAssRenderer();
    state.assTracks.clear();
    state.assCache.clear();
    await player.unload();
    clearSubtitleBlobUrls();
    const playbackId = state.episode?.id === id ? selectedStreamId(state.episode) : id;
    const playback = await api('/api/play/' + encodeURIComponent(playbackId), {method:'POST', body:{platform:state.fairPlay ? 'safari' : 'firefox'}});
    streamOpened = true;
    let source = playback.url;
    if (state.fairPlay) {
      state.fairPlayPlayback = playback;
      const response = await fetch(source, {headers: {'X-Local-Player': '1'}});
      if (!response.ok) throw new Error('HLS playlist download failed.');
      state.fairPlayQualities = FairPlaySupport.qualities(await response.text());
      state.fairPlayQuality = state.fairPlayQualities.includes(Number(previousQuality)) ? previousQuality : 'auto';
      source = FairPlaySupport.qualityUrl(source, state.fairPlayQuality);
    }
    await player.load(source, resumeTime > 0 ? resumeTime : undefined,
      state.fairPlay ? 'application/x-mpegurl' : undefined);
    await addPlaybackSubtitles(player, playback.subtitles);
    $('player-cover').classList.add('hidden'); updateQualities(); updateSubtitles();
    if (!state.fairPlay && previousQuality !== 'auto' && [...$('quality').options].some((option) => option.value === previousQuality)) { $('quality').value = previousQuality; $('quality').dispatchEvent(new Event('change')); }
    const savedSubtitle = SubtitlePreference.read(localStorage);
    const selectedSubtitle = SubtitlePreference.choose(player.getTextTracks(), savedSubtitle ?? previousSubtitleLocale);
    if (selectedSubtitle !== null) await selectSubtitle(selectedSubtitle);
    else {
      const activeSubtitle = player.getTextTracks().find((item) => item.active && player.isTextTrackVisible());
      if (activeSubtitle) await selectSubtitle(String(activeSubtitle.id));
    }
    video.playbackRate = Number($('speed').value);
    await video.play().catch(() => { $('player-loading').classList.add('hidden'); playerMessage(I18n.t("Видео готово. Нажмите кнопку воспроизведения.")); });
    clearInterval(state.keepAlive);
    state.keepAlive = setInterval(() => api('/api/keepalive', { method: 'POST', body: { playhead: video.currentTime || 0 } }).catch(() => {}), 60000);
    return true;
  } catch (error) { clearAssRenderer(); if (streamOpened) await api('/api/stop', { method: 'POST' }).catch(() => {}); $('player-loading').classList.add('hidden'); $('player-cover').classList.remove('hidden'); $('cover-play').classList.remove('hidden'); playerMessage(error?.code === 6020 ? I18n.t("Браузеру недоступен DRM. На Windows откройте плеер через SSH-туннель по адресу http://127.0.0.1:8765.") : error.message || I18n.t("Не удалось воспроизвести серию.")); return false; }
}
async function stopPlayback() { clearAssRenderer(); state.assTracks.clear(); state.assCache.clear(); clearInterval(state.keepAlive); clearTimeout(state.playbackErrorTimer); clearTimeout(state.controlsTimer); $('player-loading').classList.add('hidden'); closeSettings(); if (state.player) await state.player.unload().catch(() => {}); clearSubtitleBlobUrls(); restorePlayer(); await api('/api/stop', { method: 'POST' }).catch(() => {}); }
function clearAssRenderer() {
  state.subtitleSeq++;
  state.assTrackId = '';
  state.assContent = '';
  state.assPositionKey = '';
  if (state.assRenderer) { state.assRenderer.dispose(); state.assRenderer = null; }
}
function syncFairPlaySubtitleVisibility() {
  if (!state.fairPlay || !state.player || state.safariNativeFullscreen) return;
  if (state.assTrackId || !state.player.isTextTrackVisible()) {
    for (const track of video.textTracks) {
      if (track.mode === 'showing') track.mode = 'hidden';
    }
  }
}
video.textTracks?.addEventListener('change', syncFairPlaySubtitleVisibility);
// Keep late worker frames hidden at the end without disposing the track needed for replay.
function updateAssEndVisibility() {
  const renderer = state.assRenderer;
  if (!renderer?.canvas) return;
  renderer.canvas.style.visibility = video.ended ? 'hidden' : '';
  if (video.ended) renderer.ctx?.clearRect(0, 0, renderer.canvas.width, renderer.canvas.height);
}
video.addEventListener('playing', updateAssEndVisibility);
video.addEventListener('seeked', updateAssEndVisibility);
function dialogueBottomPercent() {
  const frame = $('player-frame');
  if (state.mini || frame.classList.contains('is-idle')) return state.subtitlePosition;
  const controls = frame.querySelector('.video-controls');
  const lift = controls && frame.clientHeight ? controls.getBoundingClientRect().height / frame.clientHeight * 100 : 0;
  return Math.min(24, state.subtitlePosition + lift + 1);
}
function updateAssPosition() {
  if (!state.assRenderer || !state.assContent) return;
  const bottom = Math.round(dialogueBottomPercent() * 10) / 10;
  const key = `${state.subtitleScale}:${bottom}`;
  if (state.assPositionKey === key) return;
  state.assPositionKey = key;
  state.assRenderer.setTrack(formatAssDialogue(state.assContent, state.subtitleScale, bottom));
}
async function selectSubtitle(id) {
  if (!state.player) return;
  clearAssRenderer();
  if (id === 'off') { await state.player.setTextTrackVisibility(false); syncFairPlaySubtitleVisibility(); updateSubtitles(); return; }
  const track = state.player.getTextTracks().find((item) => String(item.id) === id);
  if (!track) { updateSubtitles(); return; }
  state.player.selectTextTrack(track);
  const language = state.assTracks.get(id);
  if (language && window.SubtitlesOctopus) {
    const seq = state.subtitleSeq;
    state.assTrackId = id;
    await state.player.setTextTrackVisibility(false);
    syncFairPlaySubtitleVisibility();
    try {
      let content = state.assCache.get(language);
      if (!content) {
        const response = await fetch(`/api/subtitle?lang=${encodeURIComponent(language)}&raw=1`, { headers: { 'X-Local-Player': '1' } });
        if (!response.ok) throw new Error(I18n.t("Не удалось загрузить ASS-субтитры."));
        content = await response.text();
        state.assCache.set(language, content);
      }
      if (content.startsWith('WEBVTT')) throw new Error(I18n.t("Этот файл содержит WebVTT."));
      if (seq !== state.subtitleSeq) return;
      state.assContent = content;
      const bottom = Math.round(dialogueBottomPercent() * 10) / 10;
      state.assPositionKey = `${state.subtitleScale}:${bottom}`;
      state.assRenderer = new SubtitlesOctopus({
        video, subContent: formatAssDialogue(content, state.subtitleScale, bottom), workerUrl: '/libass/subtitles-octopus-worker.js',
        fallbackFont: '/libass/default.woff2',
        onError: () => { if (seq === state.subtitleSeq) { clearAssRenderer(); state.player.setTextTrackVisibility(true); updateSubtitles(); } }
      });
    } catch {
      if (seq === state.subtitleSeq) { clearAssRenderer(); await state.player.setTextTrackVisibility(true); }
    }
  } else await state.player.setTextTrackVisibility(true);
  updateSubtitles();
}
window.addEventListener('pagehide', () => {
  if (state.player?.getAssetUri()) navigator.sendBeacon('/api/stop');
});
function updateQualities() {
  if (!state.player) return;
  const tracks = state.player.getVariantTracks().filter(track => track.height);
  const heights = state.fairPlay ? state.fairPlayQualities || [] : [...new Set(tracks.map(track => track.height))].sort((a, b) => b - a);
  $('quality').innerHTML = I18n.html('<option value="auto">Авто</option>') + heights.map(height => `<option value="${height}">${height}p</option>`).join('');
  $('quality').value = state.fairPlay ? state.fairPlayQuality || 'auto' : state.player.getConfiguration().abr.enabled ? 'auto' : String(tracks.find(track => track.active)?.height || 'auto');
  updateSettingsSummary();
}
function updateSubtitles() {
  if (!state.player) return;
  const tracks = state.player.getTextTracks().filter((track) => {
    const language = String(track.language || '').trim().toLowerCase();
    const label = String(track.label || '').trim().toLowerCase();
    return (!state.fairPlay || language !== 'und') && language !== 'none' && label !== 'none' && label !== 'null (none)';
  });
  const names = new Intl.DisplayNames([I18n.language], { type: 'language' });
  $('subtitles').innerHTML = I18n.html('<option value="off">Выключены</option>') + tracks.map((track) => {
    let label = track.label || track.language || I18n.t("Субтитры");
    if (track.language) {
      try { label = names.of(track.language) || label; }
      catch { /* Some Crunchyroll locale codes are not valid Intl languages. */ }
    }
    return `<option value="${escapeHtml(track.id)}">${escapeHtml(label)}</option>`;
  }).join('');
  const active = tracks.find((track) => track.active);
  $('subtitles').value = state.assTrackId || (state.player.isTextTrackVisible() && active ? String(active.id) : 'off');
  updateSettingsSummary();
}
function updateSettingsSummary() {
  $('quality-summary').textContent = $('quality').selectedOptions[0]?.textContent || I18n.t("Авто");
  $('audio-summary').textContent = $('audio').selectedOptions[0]?.textContent || I18n.t("Оригинал");
  $('speed-summary').textContent = $('speed').value === '1' ? I18n.t("Обычная") : $('speed').selectedOptions[0]?.textContent || '1×';
  $('subtitles-summary').textContent = $('subtitles').value === 'off' ? I18n.t("Выкл.") : $('subtitles').selectedOptions[0]?.textContent || I18n.t("Вкл.");
  $('subtitle-size-summary').textContent = `${Math.round(state.subtitleScale * 100)}%`;
  $('subtitle-position-summary').textContent = $('subtitle-position').selectedOptions[0]?.textContent || I18n.t("Ниже");
  $('cc-toggle').classList.toggle('active', $('subtitles').value !== 'off');
  $('cc-toggle').setAttribute('aria-label', $('subtitles').value === 'off' ? I18n.t("Включить субтитры") : I18n.t("Выключить субтитры"));
  if (state.settingsSection) renderSettingsOptions();
}
function renderSettingsOptions() {
  const select = $(state.settingsSection);
  if (!select) return;
  $('settings-heading').textContent = ({ quality: I18n.t("Качество"), audio: I18n.t("Озвучка"), speed: I18n.t("Скорость"), subtitles: I18n.t("Субтитры"), 'subtitle-size': I18n.t("Размер субтитров"), 'subtitle-position': I18n.t("Положение субтитров") })[state.settingsSection];
  $('settings-options').innerHTML = [...select.options].map((option) => `<button class="settings-option${option.value === select.value ? ' selected' : ''}" type="button" role="menuitemradio" aria-checked="${option.value === select.value}" data-value="${escapeHtml(option.value)}"><span class="settings-check">${icon('check')}</span>${escapeHtml(option.textContent)}</button>`).join('');
}
function openSettingsSection(section) {
  state.settingsSection = section;
  $('settings-root').classList.add('hidden');
  $('settings-submenu').classList.remove('hidden');
  renderSettingsOptions();
}
function closeSettings() {
  const wasOpen = !$('settings-menu').classList.contains('hidden');
  state.settingsSection = '';
  $('settings-menu').classList.add('hidden');
  $('settings-root').classList.remove('hidden');
  $('settings-submenu').classList.add('hidden');
  $('settings-toggle').setAttribute('aria-expanded', 'false');
  $('player-frame').classList.remove('menu-open');
  if (wasOpen && !video.paused) showPlayerControls();
}
function showPlayerControls() {
  const frame = $('player-frame');
  const wasIdle = frame.classList.contains('is-idle');
  frame.classList.remove('is-idle');
  if (wasIdle) updateAssPosition();
  clearTimeout(state.controlsTimer);
  if (!video.paused && $('settings-menu').classList.contains('hidden')) {
    state.controlsTimer = setTimeout(() => {
      if (!video.paused && $('settings-menu').classList.contains('hidden')) { frame.classList.add('is-idle'); updateAssPosition(); }
    }, 2600);
  }
}

$('search-input').addEventListener('input', (event) => { state.query = event.target.value.trim(); clearTimeout(state.searchTimer); state.searchTimer = setTimeout(() => { showView('discover'); search(); }, 220); });
$('search-button').addEventListener('click', () => { showView('discover'); search(); });
$('search-input').addEventListener('keydown', (event) => { if (event.key === 'Enter') { clearTimeout(state.searchTimer); showView('discover'); search(); } });
$('quick-genre').addEventListener('change', (event) => setGenre(event.target.value));
$('quick-year').addEventListener('change', (event) => setYear(event.target.value));
$('quick-age').addEventListener('change', (event) => setAge(event.target.value));
$('sort-select').addEventListener('change', (event) => { state.sort = event.target.value; search(); });
$('advanced-toggle').addEventListener('click', () => { const open = $('advanced-filters').classList.toggle('hidden') === false; $('advanced-toggle').setAttribute('aria-expanded', String(open)); });
$('apply-filters').addEventListener('click', () => search());
$('reset-filters').addEventListener('click', () => { ['year-min','year-max','episodes-min','episodes-max','seasons-min','seasons-max'].forEach((id) => $(id).value = ''); $('search-input').value = ''; state.query = ''; setGenre(''); setYear(''); setAge(''); });
$('load-more').addEventListener('click', () => { state.offset += state.pageSize; search(true); });
$('feature-open').addEventListener('click', () => state.featured && openSeries(state.featured.id));

const mobileLayout = window.matchMedia('(max-width: 950px)');
mobileLayout.addEventListener('change', () => setWatchMenu(false));
let lastRememberedAt = 0;
function rememberEpisode(time = 0, throttle = false) {
  if (!state.series?.id || !state.episode?.id) return;
  if (throttle && (video.seeking || Date.now() - lastRememberedAt < 5000)) return;
  lastRememberedAt = Date.now();
  CrunchyResume.write(localStorage, {seriesId: state.series.id, seasonId: state.currentSeason,
    episodeId: state.episode.id, shikiId: state.shikiTarget || state.forcedShikiId,
    shikiTitle: state.forcedShikiTitle, time: video.ended ? 0 : time});
  $('nav-current').disabled = false;
}
async function resumeLastEpisode() {
  if (state.series && state.episode) { showView('watch'); return; }
  const last = CrunchyResume.read(localStorage);
  if (!last) return;
  await openSeries(last.seriesId, last.shikiId, last.shikiTitle,
    {view: 'watch', seasonId: last.seasonId, episodeId: last.episodeId, resumeTime: last.time});
}
window.addEventListener('pagehide', () => rememberEpisode(video.currentTime));
video.addEventListener('pause', () => { if (video.currentTime > 0) rememberEpisode(video.currentTime); });
let remoteLoginActive = false;
let remoteOfficialVisible = false;
let remoteLoginGeneration = 0;
let remoteLoginTimer;
let remoteInputQueue = Promise.resolve();
async function remoteInput(input) {
  if (!remoteLoginActive) return;
  const generation = remoteLoginGeneration;
  remoteInputQueue = remoteInputQueue.then(async () => {
    if (!remoteLoginActive || generation !== remoteLoginGeneration) return;
    await api('/api/login/input', {method:'POST',body:{input}});
  }).catch(error => {if(remoteLoginActive && generation === remoteLoginGeneration)remoteLoginError(error);});
  return remoteInputQueue;
}
function remoteLoginError(error) {
  remoteLoginActive = false; clearTimeout(remoteLoginTimer);$('remote-password').value='';
  $('account-error').textContent = error.message || I18n.t("Окно входа недоступно.");
  $('account-error').classList.remove('hidden');
  $('remote-login-view').classList.add('hidden');
  $('remote-login-card').classList.remove('hidden');
  api('/api/login/cancel', {method:'POST',body:{}}).catch(() => {});
}
async function pollRemoteLogin(generation) {
  if (!remoteLoginActive || generation !== remoteLoginGeneration) return;
  try {
    const result = await api('/api/login/frame', {method:'POST',body:{input:{show:remoteOfficialVisible}}});
    if (!remoteLoginActive || generation !== remoteLoginGeneration) return;
    if (result.connected) {remoteLoginActive=false;$('remote-login-view').classList.add('hidden');afterLogin();return;}
    if (result.status === 'interaction' && !remoteOfficialVisible) $('remote-login-hint').textContent=I18n.t("Вход пока не завершён. Если нужна CAPTCHA или проверка ошибки, нажмите «Открыть окно проверки».");
    if (result.image && remoteOfficialVisible) {$('remote-official').classList.remove('hidden');$('remote-login-image').src=result.image;$('remote-login-hint').textContent=I18n.t("Нажмите поле на экране и вводите текст. Для повторного открытия клавиатуры нажмите «Клавиатура». Если CAPTCHA повторяется, серверный браузер не принят сервисом.");}
    remoteLoginTimer = setTimeout(() => pollRemoteLogin(generation),1500);
  } catch (error) {if(remoteLoginActive && generation === remoteLoginGeneration)remoteLoginError(error);}
}
async function cancelRemoteLogin() {
  remoteLoginActive=false;remoteOfficialVisible=false;$('remote-official').classList.add('hidden');remoteLoginGeneration++;clearTimeout(remoteLoginTimer);
  $('remote-text').value='';$('remote-password').value='';$('remote-login-image').removeAttribute('src');
  $('remote-login-view').classList.add('hidden');
  $('remote-login-card').classList.toggle('hidden',state.connected);
  await api('/api/login/cancel',{method:'POST',body:{}}).catch(() => {});
}
$('remote-login-start').addEventListener('click',async () => {
  $('account-error').classList.add('hidden');
  const button=$('remote-login-start');button.disabled=true;
  try {
    await api('/api/login/start',{method:'POST',body:{}});
    remoteLoginActive=true;remoteOfficialVisible=false;$('remote-official').classList.add('hidden');remoteLoginGeneration++;
    $('remote-login-card').classList.add('hidden');$('remote-login-view').classList.remove('hidden');
    pollRemoteLogin(remoteLoginGeneration);
  } catch(error) {remoteLoginError(error);} finally {button.disabled=false;}
});
// Keep one invisible character so mobile keyboards can issue backspace on
// this input even though typed text is immediately forwarded and cleared.
const remoteKeyboardSentinel = '\u200b';
function focusRemoteKeyboard() {
  const input=$('remote-text');
  input.value=remoteKeyboardSentinel;
  input.focus({preventScroll:true});
  input.setSelectionRange(input.value.length,input.value.length);
}
function forwardRemoteText(input) {
  const text=input.value.replaceAll(remoteKeyboardSentinel,'');
  input.value=remoteKeyboardSentinel;
  if(text)remoteInput({type:'text',text});
}
$('remote-login-image').addEventListener('click',(event) => {
  const rect=event.currentTarget.getBoundingClientRect();
  remoteInput({type:'click',x:(event.clientX-rect.left)*390/rect.width,y:(event.clientY-rect.top)*680/rect.height});
  // Focus synchronously within the tap so mobile browsers open the keyboard.
  focusRemoteKeyboard();
});
$('remote-show-browser').addEventListener('click',() => {remoteOfficialVisible=true;$('remote-official').classList.remove('hidden');});
$('remote-keyboard').addEventListener('click',focusRemoteKeyboard);
$('remote-fill').addEventListener('click',async () => {
  const email=$('remote-email').value.trim(),password=$('remote-password').value;
  if(!remoteLoginActive || !email || !password) {
    $('remote-login-hint').textContent=I18n.t("Введите email и пароль.");return;
  }
  const button=$('remote-fill');button.disabled=true;
  try {
    await remoteInputQueue;
    await api('/api/login/input',{method:'POST',body:{input:{type:'credentials',email,password}}});
    $('remote-login-hint').textContent=I18n.t("Форма отправлена. Ожидаем подтверждения входа…");
  } catch(error) {
    $('remote-login-hint').textContent=error.message || I18n.t("Не удалось заполнить официальный вход.");
  } finally { $('remote-password').value='';button.disabled=false; }
});

$('remote-text').addEventListener('beforeinput',event => {
  if(event.inputType==='deleteContentBackward') {
    event.preventDefault();remoteInput({type:'key',key:'Backspace'});
  }
});
$('remote-text').addEventListener('input',event => {
  if(!event.isComposing)forwardRemoteText(event.target);
});
$('remote-text').addEventListener('compositionend',event => forwardRemoteText(event.target));
$('remote-text').addEventListener('keydown',event => {
  if(!event.isComposing && ['Backspace','Enter','Tab','ArrowLeft','ArrowRight'].includes(event.key)) {
    event.preventDefault();remoteInput({type:'key',key:event.key});
  }
});
$('remote-scroll-up').addEventListener('click',() => remoteInput({type:'scroll',delta:-300}));
$('remote-scroll-down').addEventListener('click',() => remoteInput({type:'scroll',delta:300}));
$('remote-enter').addEventListener('click',() => remoteInput({type:'key',key:'Enter'}));
$('remote-login-cancel').addEventListener('click',cancelRemoteLogin);
$('account-dialog').addEventListener('close',() => {if(remoteLoginActive)cancelRemoteLogin();});
window.addEventListener('pagehide',() => {if(remoteLoginActive) fetch('/api/login/cancel',{method:'POST',headers:{'X-Local-Player':'1','Content-Type':'application/json'},body:'{}',keepalive:true}).catch(() => {});});

$('feature-details').addEventListener('click', () => state.featured && openAnimeInformation(state.featured.id));
$('feature-dots').addEventListener('click', (event) => { const button = event.target.closest('[data-feature-index]'); if (!button) return; state.featuredIndex = Number(button.dataset.featureIndex); renderFeatured(); });
$('brand-home').addEventListener('click', () => showView('discover'));
$('nav-discover').addEventListener('click', () => showView('discover'));
$('nav-list').addEventListener('click', () => showView('list'));
$('nav-current').addEventListener('click', resumeLastEpisode);
$('menu-toggle').addEventListener('click', () => { if (state.view === 'watch' || mobileLayout.matches) setWatchMenu(!document.body.classList.contains('watch-menu-open')); else { state.sidebarCollapsed = !state.sidebarCollapsed; $('sidebar').classList.toggle('collapsed', state.sidebarCollapsed); $('menu-toggle').setAttribute('aria-expanded', String(!state.sidebarCollapsed)); $('menu-toggle').setAttribute('aria-label', state.sidebarCollapsed ? I18n.t("Показать меню") : I18n.t("Скрыть меню")); } });
$('sidebar-scrim').addEventListener('click', () => setWatchMenu(false));
$('mini-return').addEventListener('click', () => showView('watch'));
$('mini-toggle').addEventListener('click', () => { if (video.paused) video.play(); else video.pause(); });
$('mini-close').addEventListener('click', async () => { await stopPlayback(); $('player-cover').classList.remove('hidden'); $('cover-play').classList.toggle('hidden', !state.episode); });
$('episodes-tab').addEventListener('click', () => setWatchSideTab('episodes'));
$('similar-tab').addEventListener('click', () => setWatchSideTab('similar'));
$('season-select').addEventListener('change', (event) => loadSeason(event.target.value));
$('watch-season-link').addEventListener('click', openSeasonPage);
$('season-back').addEventListener('click', () => showView('watch'));
$('season-play-first').addEventListener('click', () => { if (!state.episodes.length) return; showView('watch'); selectEpisode(state.episodes[0].id); });
$('list-provider').addEventListener('change', (event) => { setProvider(event.target.value); loadShikiList(); if (state.series) { renderShikiControls(); refreshRatings(); } });
$('list-refresh').addEventListener('click', () => loadShikiList(true));
$('list-settings').addEventListener('click', showShikiDialog);
$('list-connect').addEventListener('click', showShikiDialog);
$('shiki-button').addEventListener('click', showShikiDialog);
$('watch-shiki-connect').addEventListener('click', showShikiDialog);
document.querySelectorAll('.list-tab').forEach((tab) => tab.addEventListener('click', () => { state.listFilter = tab.dataset.status; document.querySelectorAll('.list-tab').forEach((item) => item.classList.toggle('active', item === tab)); loadShikiList(); }));
$('shiki-provider-select').addEventListener('change', (event) => setProvider(event.target.value));
$('shiki-authorize').addEventListener('click', async () => {
  $('shiki-error').classList.add('hidden');
  try {
    const result = await api('/api/shiki/start', { method: 'POST', body: { provider: state.provider, domain: state.provider === 'rip' ? $('shiki-mirror-select').value : undefined } });
    location.assign(result.url);
  } catch (error) { $('shiki-error').textContent = error.message; $('shiki-error').classList.remove('hidden'); }
});
$('shiki-disconnect').addEventListener('click', async () => { state.shikiStatus = await api('/api/shiki/disconnect', { method: 'POST', body: { provider: state.provider } }); state.shikiItems[state.provider] = null; updateShikiStatusUI(); loadShikiList(); renderShikiControls(); });
$('shiki-target').addEventListener('change', async (event) => { state.shikiTarget = Number(event.target.value) || 0; state.watchedKey = ''; if (state.series && state.currentSeason) { const key = seasonMapKey(state.provider, state.series.id, state.currentSeason); if (state.shikiTarget) localStorage.setItem(key, String(state.shikiTarget)); else localStorage.removeItem(key); } saveRoute(); const poster = state.seasonMatch?.items.find((item) => item.mal_id === state.shikiTarget)?.poster; if (poster) setPoster($('cover-image'), poster, state.series?.poster || state.series?.wide || ''); state.seasonRatingId = state.shikiTarget; updateSeasonPresentation(); refreshRatings(); shikiMessage(''); await loadCurrentRate(); });
$('shiki-save-rate').addEventListener('click', () => saveShikiRate({ status: $('shiki-rate-status').value, episodes: Number($('shiki-episodes').value), score: Number($('shiki-score').value) }));
$('shiki-mark-watched').addEventListener('click', () => markWatched());
$('account-button').addEventListener('click', () => { $('account-dialog').showModal(); window.postMessage({ source: 'crunchy-local-page', type: 'PING' }, location.origin); });
$('account-dialog').querySelector('form').addEventListener('submit', (event) => event.preventDefault());
$('shiki-dialog').querySelector('form').addEventListener('submit', (event) => event.preventDefault());
document.querySelectorAll('dialog .close-button').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
function afterLogin() { setConnected(true); $('cookie-input').value = ''; $('cookie-file').value = ''; $('cookie-file-label').textContent = I18n.t("Выбрать файл"); $('browser-login-status').classList.add('hidden'); $('extension-login-button').disabled = false; if ($('account-dialog').open) $('account-dialog').close(); if (state.view === 'watch' && state.series && !state.seasons.length) openSeries(state.series.id, state.shikiTarget || state.forcedShikiId, state.forcedShikiTitle); else if (state.currentSeason && !state.episodes.length) loadSeason(state.currentSeason); else if (state.episode) startPlayback(state.episode.id); }
window.addEventListener('focus', async () => { if (state.connected) return; try { if ((await api('/api/status')).connected) afterLogin(); } catch { /* The server may be restarting. */ } });
let loginBridgeTimer;
$('extension-login-button').addEventListener('click', () => { $('account-error').classList.add('hidden'); $('extension-login-button').disabled = true; $('browser-login-status').textContent = I18n.t("Проверяем вход на Crunchyroll…"); $('browser-login-status').classList.remove('hidden'); clearTimeout(loginBridgeTimer); if (loginIntegration === 'tampermonkey') loginBridgeTimer = setTimeout(() => { $('extension-login-button').disabled = false; $('browser-login-status').classList.add('hidden'); $('account-error').textContent = I18n.t('Скрипт Tampermonkey не ответил. Обновите скрипт и перезагрузите страницу.'); $('account-error').classList.remove('hidden'); }, 10000); window.postMessage(loginIntegration === 'tampermonkey' ? JSON.stringify({source: 'crunchy-local-page', type: 'USERSCRIPT_LOGIN'}) : {source: 'crunchy-local-page', type: 'LOGIN'}, location.origin); });
window.addEventListener('message', (event) => {
  if (event.source !== window || event.origin !== location.origin) return;
  let message = event.data;
  if (typeof message === 'string') { if (message.length > 4000) return; try { message = JSON.parse(message); } catch { return; } }
  if (message?.source !== 'crunchy-local-extension') return;
  if (['CHECKING', 'WAITING', 'CONNECTING', 'CONNECTED', 'ERROR'].includes(message.type)) clearTimeout(loginBridgeTimer);
  if (message.type === 'READY') { if (message.provider === 'tampermonkey') loginIntegration = 'tampermonkey'; extensionAvailable = true; setConnected(state.connected); }
  if (message.type === 'CHECKING') $('browser-login-status').textContent = I18n.t("Проверяем доступ Tampermonkey к cookie…");
  if (message.type === 'WAITING') $('browser-login-status').textContent = I18n.t("Введите логин и пароль на открывшейся странице Crunchyroll. После входа вернитесь сюда.");
  if (message.type === 'CONNECTING') $('browser-login-status').textContent = I18n.t("Подключаем сеанс Crunchyroll…");
  if (message.type === 'CONNECTED') afterLogin();
  if (message.type === 'ERROR') { $('extension-login-button').disabled = false; $('browser-login-status').classList.add('hidden'); $('account-error').textContent = I18n.translate(message.message || '') || I18n.t("Не удалось войти в Crunchyroll."); $('account-error').classList.remove('hidden'); }
});
$('connect-button').addEventListener('click', async () => { $('account-error').classList.add('hidden'); $('connect-button').disabled = true; try { await api('/api/connect', { method: 'POST', body: { cookie: $('cookie-input').value.trim() } }); afterLogin(); } catch (error) { $('account-error').textContent = error.message; $('account-error').classList.remove('hidden'); } finally { $('connect-button').disabled = false; } });
$('cookie-file').addEventListener('change', async (event) => { const file = event.target.files?.[0]; if (!file) return; $('cookie-file-label').textContent = file.name; try { if (file.size > 2_000_000) throw new Error(I18n.t("Файл cookies.txt слишком большой.")); const rows = (await file.text()).split(/\r?\n/).map((line) => line.split('\t')); const token = rows.find((parts) => parts.length > 6 && parts[5] === 'etp_rt')?.[6]; if (!token) throw new Error(I18n.t("В файле не найден cookie etp_rt для crunchyroll.com.")); $('cookie-input').value = token; $('connect-button').click(); } catch (error) { $('account-error').textContent = error.message; $('account-error').classList.remove('hidden'); } });
$('disconnect-button').addEventListener('click', async () => { await stopPlayback(); await api('/api/disconnect', { method: 'POST' }); setConnected(false); $('account-dialog').close(); $('player-cover').classList.remove('hidden'); });
$('cover-play').addEventListener('click', () => state.episode && selectEpisode(state.episode.id));
$('play-toggle').addEventListener('click', () => { if (video.paused) { if (state.episode && !state.player?.getAssetUri()) startPlayback(state.episode.id); else video.play(); } else video.pause(); showPlayerControls(); });
$('next-episode').addEventListener('click', () => { const index = state.episodes.findIndex((item) => item.id === state.episode?.id); if (index >= 0 && index < state.episodes.length - 1) selectEpisode(state.episodes[index + 1].id); });
$('back-ten').addEventListener('click', () => { video.currentTime = Math.max(0, video.currentTime - 10); });
$('forward-ten').addEventListener('click', () => { video.currentTime = Math.min(video.duration || Infinity, video.currentTime + 10); });
$('seek').addEventListener('input', (event) => { if (video.duration) video.currentTime = Number(event.target.value) / 100 * video.duration; showPlayerControls(); });
$('volume').addEventListener('input', (event) => { video.volume = Number(event.target.value) / 100; video.muted = false; });
$('mute-toggle').addEventListener('click', () => { video.muted = !video.muted; });
$('fullscreen').addEventListener('click', () => {
  if (document.fullscreenElement) document.exitFullscreen();
  else if (video.webkitDisplayingFullscreen) video.webkitExitFullscreen();
  else if (typeof $('player-frame').requestFullscreen === 'function') $('player-frame').requestFullscreen();
  else if (typeof video.webkitEnterFullscreen === 'function') video.webkitEnterFullscreen();
});
video.addEventListener('webkitbeginfullscreen', () => {state.safariNativeFullscreen = true; if (state.assTrackId) state.player?.setTextTrackVisibility(true);});
video.addEventListener('webkitendfullscreen', () => {state.safariNativeFullscreen = false; if (state.assTrackId) state.player?.setTextTrackVisibility(false); syncFairPlaySubtitleVisibility();});
$('cc-toggle').addEventListener('click', () => { if ($('subtitles').value === 'off') { const options = [...$('subtitles').options]; const preferred = options.find((option) => (I18n.language==='ru' ? /русск|russian/i : /english|английск/i).test(option.textContent)) || options[1]; if (preferred) $('subtitles').value = preferred.value; } else $('subtitles').value = 'off'; $('subtitles').dispatchEvent(new Event('change')); updateSettingsSummary(); });
$('settings-toggle').addEventListener('click', () => { const opening = $('settings-menu').classList.contains('hidden'); if (!opening) { closeSettings(); showPlayerControls(); return; } $('settings-menu').classList.remove('hidden'); $('settings-toggle').setAttribute('aria-expanded', 'true'); $('player-frame').classList.add('menu-open'); showPlayerControls(); });
document.querySelectorAll('.settings-row').forEach((row) => row.addEventListener('click', () => openSettingsSection(row.dataset.setting)));
$('settings-back').addEventListener('click', () => { state.settingsSection = ''; $('settings-submenu').classList.add('hidden'); $('settings-root').classList.remove('hidden'); });
$('settings-options').addEventListener('click', (event) => { const button = event.target.closest('.settings-option'); if (!button) return; const select = $(state.settingsSection); select.value = button.dataset.value; select.dispatchEvent(new Event('change')); updateSettingsSummary(); closeSettings(); showPlayerControls(); });
$('player-frame').addEventListener('pointermove', showPlayerControls);
$('player-frame').addEventListener('focusin', showPlayerControls);
$('player-frame').addEventListener('keydown', showPlayerControls);
$('player-frame').addEventListener('pointerleave', () => { if (!video.paused && $('settings-menu').classList.contains('hidden')) { clearTimeout(state.controlsTimer); state.controlsTimer = setTimeout(() => { $('player-frame').classList.add('is-idle'); updateAssPosition(); }, 700); } });
video.addEventListener('click', () => { if (state.mini) showView('watch'); else $('play-toggle').click(); });
video.addEventListener('dblclick', () => $('fullscreen').click());
document.addEventListener('click', (event) => { if (!$('settings-menu').classList.contains('hidden') && !$('settings-menu').contains(event.target) && !$('settings-toggle').contains(event.target)) closeSettings(); });
$('speed').addEventListener('change', (event) => { video.playbackRate = Number(event.target.value); });
$('audio').addEventListener('change', async (event) => {
  if (!state.episode) return;
  const next = event.target.value;
  const previous = state.audioLocale;
  if (next === previous) return;
  if (state.audioSwitching) { event.target.value = previous; return; }
  state.audioLocale = next;
  updateSettingsSummary();
  if (!state.player?.getAssetUri()) { localStorage.setItem('crunchy-audio-locale', next); return; }
  state.audioSwitching = true;
  const episodeId = state.episode.id;
  const position = video.currentTime;
  const switched = await startPlayback(episodeId, position);
  if (state.episode?.id === episodeId) {
    if (switched) localStorage.setItem('crunchy-audio-locale', next);
    else { state.audioLocale = previous; $('audio').value = previous; await startPlayback(episodeId, position); }
    updateSettingsSummary();
  }
  state.audioSwitching = false;
});
$('quality').addEventListener('change', (event) => { if (!state.player) return; const height = event.target.value; if (state.fairPlay) { changeFairPlayQuality(height); return; } state.player.configure({ abr: { enabled: height === 'auto' } }); if (height !== 'auto') { const track = state.player.getVariantTracks().filter((x) => x.height === Number(height)).sort((a, b) => b.bandwidth - a.bandwidth)[0]; if (track) state.player.selectVariantTrack(track, true); } });
$('subtitles').addEventListener('change', async (event) => {
  const id = event.target.value;
  const track = state.player?.getTextTracks().find((item) => String(item.id) === id);
  if (id === 'off' || track?.language) SubtitlePreference.write(localStorage, id === 'off' ? 'off' : track.language);
  await selectSubtitle(id);
});
$('subtitle-size').addEventListener('change', async (event) => {
  const scale = Number(event.target.value);
  if (![0.75, 0.9, 1, 1.1, 1.25, 1.5].includes(scale)) return;
  state.subtitleScale = scale;
  localStorage.setItem('crunchy-subtitle-size', String(scale));
  state.player?.configure({ textDisplayer: { fontScaleFactor: scale } });
  if (state.assTrackId) await selectSubtitle(state.assTrackId);
  updateSettingsSummary();
});
$('subtitle-position').addEventListener('change', (event) => {
  const position = Number(event.target.value);
  if (![1, 2, 4, 6, 10].includes(position)) return;
  state.subtitlePosition = position;
  localStorage.setItem('crunchy-subtitle-position', String(position));
  updateAssPosition();
  updateSettingsSummary();
});
document.addEventListener('fullscreenchange', updateAssPosition);
window.addEventListener('resize', updateAssPosition);
video.addEventListener('timeupdate', () => { rememberEpisode(video.currentTime, true); const progress = video.duration ? video.currentTime / video.duration * 100 : 0; $('seek').value = String(progress); $('seek').style.setProperty('--progress', `${progress}%`); $('mini-progress-fill').style.width = `${progress}%`; $('time-label').textContent = `${formatTime(video.currentTime)} / ${formatTime(video.duration)}`; if (video.currentTime > state.lastMediaTime + 0.2 && !$('player-message').classList.contains('hidden')) clearPlayerMessage(); if (state.playbackRecoveryAttempts && video.currentTime > state.recoveryTime + 30) state.playbackRecoveryAttempts = 0; state.lastMediaTime = video.currentTime; });
video.addEventListener('play', () => { $('play-toggle').innerHTML = icon('pause'); $('play-toggle').setAttribute('aria-label', I18n.t("Пауза")); updateMiniInfo(); showPlayerControls(); });
video.addEventListener('pause', () => { $('play-toggle').innerHTML = icon('play_arrow'); $('play-toggle').setAttribute('aria-label', I18n.t("Воспроизвести")); updateMiniInfo(); showPlayerControls(); });
video.addEventListener('volumechange', () => { $('mute-toggle').innerHTML = icon(video.muted || !video.volume ? 'volume_off' : 'volume_up'); $('mute-toggle').setAttribute('aria-label', video.muted ? I18n.t("Включить звук") : I18n.t("Выключить звук")); });
video.addEventListener('waiting', () => { if (!$('player-cover').classList.contains('hidden')) return; $('player-loading').classList.remove('hidden'); });
video.addEventListener('playing', () => { $('player-loading').classList.add('hidden'); clearPlayerMessage(); showPlayerControls(); });
video.addEventListener('ended', () => { updateAssEndVisibility(); markWatched(true); const i = state.episodes.findIndex((x) => x.id === state.episode?.id); if (i >= 0 && i < state.episodes.length - 1) selectEpisode(state.episodes[i + 1].id); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !$('settings-menu').classList.contains('hidden')) { closeSettings(); return; } if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) || $('account-dialog').open || $('shiki-dialog').open) return; if (event.key === '/') { event.preventDefault(); $('search-input').focus(); } if (state.view === 'watch') { if (event.code === 'Space') { event.preventDefault(); $('play-toggle').click(); } if (event.key === 'ArrowLeft') { event.preventDefault(); $('back-ten').click(); } if (event.key === 'ArrowRight') { event.preventDefault(); $('forward-ten').click(); } if (event.key.toLowerCase() === 'f') $('fullscreen').click(); } });

function informationStatus(target, message, retry) {
  $(target).innerHTML=`<p class="anime-info-status">${escapeHtml(I18n.t(message))}</p>${retry ? `<button class="outline-button info-retry" type="button">${escapeHtml(I18n.t("Повторить загрузку"))}</button>` : ''}`;
  $(target).querySelector('.info-retry')?.addEventListener('click',retry);
}
function informationMarkup(data) {
  const link=(href,label)=>href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)} ${icon('open_in_new')}</a>` : escapeHtml(label);
  const facts=[['Студии',data.studios?.join(', ')],['Жанры',data.genres?.join(' · ')],['Дата выхода',data.aired],['Формат',data.kind],['Статус',data.status],['Длительность серии',typeof data.duration==='number' ? I18n.t("{0} мин.",data.duration) : data.duration]];
  const statuses={tv:'ТВ-сериал',movie:'Фильм',ova:'OVA',ona:'ONA',special:'Спецвыпуск',music:'Музыкальное видео',released:'Вышло',ongoing:'Выходит',anons:'Анонс',finished_airing:'Вышло',currently_airing:'Выходит',not_yet_aired:'Анонс', 'Finished Airing':'Вышло','Currently Airing':'Выходит','Not yet aired':'Анонс'};
  const scoreTitle=data.source==='Shikimori' ? I18n.t('Средняя оценка пользователей Shikimori') : data.source;
  const scoreLink=data.score==null ? '' : `<a class="rating-link" href="${escapeHtml(data.score_url || data.source_url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(scoreTitle)}">${escapeHtml(data.source)} <strong>${escapeHtml(data.score.toFixed(2))} / 10</strong></a>`;
  const malScore=data.source==='Shikimori' && data.mal_score!=null ? `<a class="rating-link" href="https://myanimelist.net/anime/${data.id}" target="_blank" rel="noopener noreferrer">MAL <strong>${escapeHtml(data.mal_score.toFixed(2))} / 10</strong></a>` : '';
  return `<section class="anime-facts"><h2>${escapeHtml(I18n.t("Информация"))}</h2><div class="anime-info-ratings">${scoreLink}${malScore}</div><dl>${facts.filter(([,value])=>value).map(([label,value])=>`<div><dt>${escapeHtml(I18n.t(label))}</dt><dd>${escapeHtml(I18n.t(statuses[value]||value))}</dd></div>`).join('')}</dl><p class="anime-info-source">${escapeHtml(I18n.t("Источник информации"))}: ${link(data.source_url,data.source)}</p></section><section class="anime-characters"><h2>${escapeHtml(I18n.t("Персонажи"))}</h2>${data.character_source==='Shikimori' ? `<p class="anime-info-source">${escapeHtml(I18n.t("Источник информации"))}: Shikimori</p>` : ''}${data.characters?.length ? `<div class="character-grid">${data.characters.map(c=>`<a class="character-card" href="${escapeHtml(c.url || data.source_url)}" target="_blank" rel="noopener noreferrer">${c.image ? `<img class="character-image" src="${escapeHtml(c.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="character-placeholder">${icon('person')}</span>`}<strong>${escapeHtml(c.name)}</strong><small>${escapeHtml(I18n.t(c.role==='Main'?'Главный герой':c.role==='Supporting'?'Второстепенный герой':c.role))}</small></a>`).join('')}</div>` : `<p class="anime-info-status">${escapeHtml(I18n.t(data.warnings?.includes('characters') ? "Персонажи временно недоступны." : "Информация о персонажах пока отсутствует."))}</p>`}</section>`;
}
function applyInformationHero(prefix, data) {
  if(data.title)$(prefix+'-title').textContent=data.title;
  if(data.description)$(prefix+'-description').textContent=data.description;
  $(prefix+'-meta').textContent=[data.aired?.slice(0,4),data.episodes ? I18n.t("{0} серий",data.episodes) : '',data.genres?.join(' · ')].filter(Boolean).join(' · ');
  if(data.poster)setPoster($(prefix+'-poster'),data.poster,$(prefix+'-poster').src);
}
async function openAnimeInformation(id) {
  const seq=++state.infoSeq;
  try {
    const series=await api('/api/series/'+encodeURIComponent(id));
    if(seq!==state.infoSeq)return;
    state.infoSeries=series;
    $('info-title').textContent=series.title;
    $('info-meta').textContent=[series.year,...(series.genres || [])].filter(Boolean).join(' · ');
    $('info-description').textContent=series.description || I18n.t("Описание пока недоступно.");
    setPoster($('info-poster'),series.poster,series.wide);
    showView('info');
    await loadAnimeInformation();
  } catch(error){if(seq===state.infoSeq)alert(error.message);}
}
async function loadAnimeInformation() {
  const series=state.infoSeries,seq=++state.infoSeq;
  if(!series)return;
  informationStatus('info-details',"Загружаем информацию об аниме…");
  try {
    const data=await api('/api/anime-info?'+new URLSearchParams({series:series.id,mal_id:series.mal_id || 0,lang:I18n.language}));
    if(seq!==state.infoSeq || state.infoSeries?.id!==series.id)return;
    if(data.matched===false){informationStatus('info-details',"Для этого аниме пока не найдено соответствие MAL/Shikimori.");return;}
    state.infoSeries.mal_id=data.id;
    applyInformationHero('info',data);$('info-details').innerHTML=informationMarkup(data);
  } catch {if(seq===state.infoSeq)informationStatus('info-details',"Не удалось загрузить дополнительную информацию. Просмотр остаётся доступен.",loadAnimeInformation);}
}
function seasonInformationId(){return state.shikiTarget || state.seasonRatingId || 0;}
async function loadSeasonInformation() {
  const season=state.currentSeason,id=seasonInformationId(),seq=++state.seasonInfoSeq;
  state.seasonInfo=null;
  if(!id){informationStatus('season-details',"Для этого сезона пока не найдено соответствие MAL/Shikimori.");return;}
  informationStatus('season-details',"Загружаем информацию об аниме…");
  try {
    const data=await api('/api/anime-info?'+new URLSearchParams({mal_id:id,lang:I18n.language}));
    if(seq!==state.seasonInfoSeq || state.currentSeason!==season || seasonInformationId()!==id)return;
    state.seasonInfo={season,id,data};applyInformationHero('season-page',data);
    $('season-details').innerHTML=informationMarkup(data);
  } catch {if(seq===state.seasonInfoSeq)informationStatus('season-details',"Не удалось загрузить дополнительную информацию. Просмотр остаётся доступен.",loadSeasonInformation);}
}
$('info-back').addEventListener('click',()=>showView('discover'));
$('info-watch').addEventListener('click',()=>state.infoSeries && openSeries(state.infoSeries.id,state.infoSeries.mal_id || 0));

async function boot() {
  $('nav-current').disabled = !CrunchyResume.read(localStorage);
  const route = new URLSearchParams(location.search);
  setProvider(state.provider);
  await Promise.allSettled([loadFilters(), refreshShikiStatus(), api('/api/status').then((data) => { setConnected(data.connected); state.catalogVersion=data.catalog_version; $('catalog-count').textContent = I18n.t("{0} аниме",data.catalog_count.toLocaleString(I18n.locale)); })]);
  const redirect = route.get('shiki');
  if (['one','rip','mal'].includes(redirect)) { setProvider(redirect); history.replaceState(null, '', '/'); await refreshShikiStatus().catch(() => {}); showView('list'); if (state.shikiStatus[redirect]?.error) showShikiDialog(); }
  loadFeatured();
  search();
  if (!redirect && route.get('view') === 'list') {
    setProvider(route.get('provider') || state.provider);
    showView('list');
  } else if (!redirect && route.get('view')==='info' && /^[A-Z0-9]+$/.test(route.get('series') || '')) {
    await openAnimeInformation(route.get('series'));
  } else if (!redirect && ['watch', 'season'].includes(route.get('view')) && /^[A-Z0-9]+$/.test(route.get('series') || '')) {
    await openSeries(route.get('series'), Number(route.get('shiki_id')) || 0, route.get('shiki_title') || '', { view: route.get('view'), seasonId: route.get('season'), episodeId: route.get('view') === 'watch' ? route.get('episode') : null, resumeTime: CrunchyResume.matchingTime(localStorage, route.get('episode')) });
  }
}
boot();
window.postMessage({ source: 'crunchy-local-page', type: 'PING' }, location.origin);

// Refresh discovery after a published catalog update; active playback stays in place.
let checkingCatalog=false;
async function checkCatalogVersion() {
  if(document.hidden || checkingCatalog)return;
  checkingCatalog=true;
  try {
    const info=await api('/api/catalog/status');
    if(!state.catalogVersion){state.catalogVersion=info.version;return;}
    if(info.version===state.catalogVersion)return;
    state.catalogVersion=info.version;
    state.shikiItems={one:null,rip:null,mal:null};
    $('catalog-count').textContent=I18n.t("{0} аниме",info.count.toLocaleString(I18n.locale));
    await loadFilters();
    if(state.view==='discover'){await search();await loadFeatured();}
    else if(state.view==='list')await loadShikiList();
  } catch { /* A failed check leaves the current page and playback available. */ }
  finally {checkingCatalog=false;}
}
setTimeout(checkCatalogVersion,15000);
setInterval(checkCatalogVersion,300000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)checkCatalogVersion();});


(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const icons = { add: '#i-plus', selected: '#i-check', remove: '#i-close' };
  const initialState = {
    revision: -1,
    settings: { folder: '', quality: '192', ascii_names: false, source: 'YouTube' },
    results: [], basket: [], busy: 'idle', query: '', status: '', progress: 0,
    current_track: null, logs: [], summary: null, closing: false
  };
  let state = initialState;
  let connected = false;
  let initialized = false;
  let initializing = false;
  let pending = false;
  let fetching = null;
  let pollTimer = null;
  let source = 'youtube';
  let searchError = '';
  let sourceInitialized = false;
  let settingsSaving = false;
  let logSignature = '';
  let lastAnnouncement = '';
  let lastConnectionError = '';
  let searchLogBaseline = null;
  let previousSummary = '';
  const localLogs = [];
  const resultNodes = new Map();
  const basketNodes = new Map();

  const api = () => window.pywebview?.api;
  const idle = () => connected && !pending && state.busy === 'idle' && !state.closing;
  const normalizeSource = value => String(value || '').toLowerCase().includes('sound') ? 'soundcloud' : 'youtube';
  const sourceName = value => normalizeSource(value) === 'soundcloud' ? 'SoundCloud' : 'YouTube';
  const trackTitle = track => String(track.title || 'Без названия');
  const trackArtist = track => String(track.artist || 'Исполнитель не указан');

  function icon(href, small = false) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', small ? 'icon small' : 'icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', href);
    svg.append(use);
    return svg;
  }

  function duration(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) < 0) return '—';
    const seconds = Math.floor(Number(value));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` : `${minutes}:${String(seconds % 60).padStart(2, '0')}`;
  }

  function plural(count, forms) {
    const last = count % 10;
    return forms[count % 100 >= 11 && count % 100 <= 14 ? 2 : last === 1 ? 0 : last >= 2 && last <= 4 ? 1 : 2];
  }

  function toast(message, error = false) {
    const el = document.createElement('div');
    el.className = `toast${error ? ' is-error' : ''}`;
    el.append(icon(error ? '#i-error' : '#i-check'));
    const text = document.createElement('span');
    text.className = 'toast-message';
    text.textContent = String(message);
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'icon-button';
    close.setAttribute('aria-label', 'Закрыть уведомление');
    close.append(icon('#i-close', true));
    close.addEventListener('click', () => el.remove());
    el.append(text, close);
    $('toast-region').append(el);
    while ($('toast-region').children.length > 3) $('toast-region').firstElementChild.remove();
    window.setTimeout(() => el.remove(), error ? 12000 : 5500);
  }

  function recordError(message) {
    localLogs.push({ time: new Date().toLocaleTimeString('ru-RU'), text: String(message), level: 'error' });
    if (localLogs.length > 100) localLogs.shift();
    renderLogs();
    $('log-indicator').hidden = false;
  }

  function reportError(message) {
    const text = String(message || 'Не удалось выполнить действие. Подробности — в журнале событий.');
    recordError(text);
    toast(text, true);
    return text;
  }

  async function refreshState(force = false) {
    if (!api()) return false;
    if (fetching) {
      await fetching;
      return force ? refreshState(false) : connected;
    }
    fetching = (async () => {
      try {
        const next = await api().get_state();
        if (!next || typeof next.revision !== 'number' || !next.settings || !Array.isArray(next.results) || !Array.isArray(next.basket)) {
          throw new Error('Приложение вернуло некорректное состояние.');
        }
        const wasConnected = connected;
        connected = true;
        lastConnectionError = '';
        $('bridge-banner').hidden = true;
        if (next.revision >= state.revision) {
          const changed = next.revision !== state.revision || !initialized || !wasConnected;
          state = next;
          if (state.busy !== 'search' && searchLogBaseline !== null && (state.logs || []).length > searchLogBaseline) {
            const newErrors = (state.logs || []).slice(searchLogBaseline).filter(log => /error|critical|exception/i.test(String(log.level)));
            if (newErrors.length && /не удалось|ошибк/i.test(String(state.status)) && !searchError) {
              searchError = String(newErrors[newErrors.length - 1].text || 'Ошибка поиска');
              toast('Поиск не завершён. Подробности ошибки — в журнале событий.', true);
            }
            searchLogBaseline = null;
          }
          const summarySignature = state.summary ? JSON.stringify(state.summary) : '';
          if (initialized && summarySignature && summarySignature !== previousSummary && Number(state.summary.failed) > 0) {
            toast(`Не удалось скачать ${state.summary.failed} ${plural(Number(state.summary.failed), ['трек', 'трека', 'треков'])}. Подробности — в журнале событий.`, true);
          }
          previousSummary = summarySignature;
          initialized = true;
          if (!sourceInitialized) {
            source = normalizeSource(state.settings.source);
            sourceInitialized = true;
            if (!$('search-input').value && state.query) $('search-input').value = state.query;
          }
          if (changed) render();
          else renderControls();
        } else renderControls();
        return true;
      } catch (error) {
        connected = false;
        const message = String(error?.message || error);
        $('bridge-message').textContent = 'Связь с приложением прервана. Ожидаем восстановления…';
        $('bridge-banner').hidden = false;
        if (message !== lastConnectionError) {
          recordError(`Не удалось получить состояние: ${message}`);
          lastConnectionError = message;
        }
        renderControls();
        return false;
      } finally {
        fetching = null;
      }
    })();
    return fetching;
  }

  async function action(method, args = [], options = {}) {
    if (!api() || !connected) {
      toast('Запустите через start.bat, чтобы использовать эту функцию.');
      return { ok: false };
    }
    if (pending || state.closing || (state.busy !== 'idle' && method !== 'cancel_download')) return { ok: false };
    pending = true;
    renderControls();
    let result;
    try {
      result = await api()[method](...args);
      if (!result || result.ok !== true) {
        const error = reportError(result?.error || 'Не удалось выполнить действие.');
        if (options.search) searchError = error;
        if (options.settings) {
          $('settings-error').textContent = error;
          $('settings-error').hidden = false;
        }
        result = { ok: false, error };
      }
    } catch (error) {
      const message = reportError(error?.message || String(error));
      if (options.search) searchError = message;
      if (options.settings) {
        $('settings-error').textContent = message;
        $('settings-error').hidden = false;
      }
      result = { ok: false, error: message };
    } finally {
      await refreshState(true);
      pending = false;
      render();
    }
    return result;
  }

  function createTrackNode(track, basket = false) {
    const el = document.createElement('div');
    el.className = basket ? 'basket-track' : 'track-row';
    el.setAttribute('role', 'listitem');
    const cover = document.createElement('div');
    cover.className = 'track-cover';
    cover.setAttribute('aria-hidden', 'true');
    let hash = 0;
    for (const character of String(track.identifier || track.url || '')) hash = ((hash << 5) - hash + character.charCodeAt(0)) | 0;
    const hues = [86, 146, 186, 263, 30];
    cover.style.setProperty('--hue', String(hues[Math.abs(hash) % hues.length]));
    cover.append(icon(Math.abs(hash) % 2 ? '#i-wave' : '#i-note'));
    const info = document.createElement('div');
    info.className = 'track-info';
    const title = document.createElement('span');
    title.className = 'track-title';
    const artist = document.createElement('span');
    artist.className = 'track-artist';
    info.append(title, artist);
    const time = document.createElement('span');
    time.className = 'track-duration';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = basket ? 'icon-button' : 'track-select';
    button.append(icon(basket ? icons.remove : icons.add, basket));
    button.addEventListener('click', () => {
      if (!idle()) return;
      if (basket) action('remove_track', [track.url]);
      else action('set_selected', [track.url, !state.basket.some(item => item.url === track.url)]);
    });
    el.append(cover, info);
    if (!basket) el.append(time);
    el.append(button);
    return { el, title, artist, time, button, use: button.querySelector('use') };
  }

  function syncTracks(container, map, tracks, basket = false) {
    const selected = new Set(state.basket.map(track => track.url));
    const live = new Set();
    tracks.forEach((track, index) => {
      const key = String(track.url);
      if (live.has(key)) return;
      live.add(key);
      let node = map.get(key);
      if (!node) {
        node = createTrackNode(track, basket);
        map.set(key, node);
      }
      const title = trackTitle(track);
      const artist = trackArtist(track);
      if (node.title.textContent !== title) node.title.textContent = title;
      if (node.artist.textContent !== artist) node.artist.textContent = artist;
      node.title.title = title;
      node.artist.title = artist;
      node.time.textContent = duration(track.duration);
      node.button.disabled = !idle();
      if (basket) {
        node.button.setAttribute('aria-label', `Убрать из подборки: ${title}`);
        node.button.title = 'Убрать из подборки';
      } else {
        const isSelected = selected.has(track.url);
        node.el.classList.toggle('is-selected', isSelected);
        node.button.setAttribute('aria-pressed', String(isSelected));
        node.button.setAttribute('aria-label', `${isSelected ? 'Убрать из подборки' : 'Добавить в подборку'}: ${title}`);
        node.button.title = isSelected ? 'Убрать из подборки' : 'Добавить в подборку';
        node.use.setAttribute('href', isSelected ? icons.selected : icons.add);
      }
      if (container.children[index] !== node.el) container.insertBefore(node.el, container.children[index] || null);
    });
    for (const [key, node] of map) {
      if (!live.has(key)) {
        node.el.remove();
        map.delete(key);
      }
    }
  }

  function renderResults() {
    const searching = state.busy === 'search';
    const hasResults = state.results.length > 0 && !searching && !searchError;
    $('results-count').textContent = String(searching || searchError ? 0 : state.results.length);
    $('results-scroll').setAttribute('aria-busy', String(searching));
    $('results-list').hidden = !hasResults;
    $('search-empty').hidden = hasResults;
    $('search-empty').classList.toggle('is-searching', searching);
    $('results-context').hidden = !state.query || searching;
    if (state.query) $('results-context').textContent = `${sourceName(state.settings.source)} · «${state.query}»`;
    const emptyTitle = $('empty-title');
    const emptyDescription = $('empty-description');
    $('empty-action').hidden = searching;
    if (searching) {
      emptyTitle.textContent = 'Ищем ваш звук…';
      emptyDescription.textContent = 'Проверяем источник и собираем результаты. Это может занять немного времени.';
    } else if (searchError) {
      emptyTitle.textContent = 'Не удалось выполнить поиск';
      emptyDescription.textContent = 'Проверьте подключение и попробуйте ещё раз. Подробности ошибки доступны в журнале событий.';
      $('empty-action').textContent = 'Попробовать снова →';
    } else if (state.query && !hasResults) {
      emptyTitle.textContent = 'Пока ничего не нашлось';
      emptyDescription.textContent = 'Попробуйте другое название или смените источник поиска.';
      $('empty-action').textContent = 'Изменить запрос →';
    } else {
      emptyTitle.textContent = 'Что будем слушать?';
      emptyDescription.textContent = 'Введите название трека или имя исполнителя. Ваша следующая находка — в одном поиске.';
      $('empty-action').textContent = 'Начать поиск →';
    }
    syncTracks($('results-list'), resultNodes, state.results);
  }

  function renderBasket() {
    const count = state.basket.length;
    $('basket-count').textContent = String(count);
    $('download-count').textContent = String(count);
    $('basket-empty').hidden = count > 0;
    $('basket-list').hidden = count === 0;
    const known = state.basket.filter(track => track.duration != null && Number.isFinite(Number(track.duration)) && Number(track.duration) >= 0);
    const seconds = known.reduce((sum, track) => sum + Number(track.duration), 0);
    const time = seconds ? ` · ${known.length < count ? '≥ ' : ''}${Math.max(1, Math.round(seconds / 60))} мин` : '';
    $('basket-duration').textContent = count ? `${count} ${plural(count, ['трек', 'трека', 'треков'])}${time}` : 'Пока ни одного трека';
    $('export-quality').textContent = `MP3 · ${state.settings.quality} кбит/с`;
    syncTracks($('basket-list'), basketNodes, state.basket, true);
  }

  function renderDock() {
    const downloading = state.busy === 'download';
    document.body.classList.toggle('is-downloading', downloading);
    const progress = Math.max(0, Math.min(1, Number(state.progress) || 0));
    const percent = Math.round(progress * 100);
    $('progress-track').hidden = !downloading;
    $('progress-value').hidden = !downloading;
    $('progress-value').textContent = `${percent}%`;
    $('progress-track').setAttribute('aria-valuenow', String(percent));
    $('progress-fill').style.width = `${percent}%`;
    $('download-button').hidden = downloading;
    $('cancel-button').hidden = !downloading;
    let title;
    let description;
    let symbol = '#i-download';
    if (state.closing) {
      title = 'Завершаем работу…';
      description = 'Ожидаем безопасного завершения текущей операции.';
    } else if (downloading) {
      title = state.current_track ? trackTitle(state.current_track) : 'Сохраняем вашу музыку…';
      description = state.status || 'Загрузка и преобразование в MP3';
      symbol = '#i-wave';
    } else if (state.busy === 'search') {
      title = 'Находим музыку для вас';
      description = state.status || 'Идёт поиск. Подборка останется на месте.';
      symbol = '#i-search';
    } else if (state.summary) {
      const saved = Number(state.summary.saved) || 0;
      const failed = Number(state.summary.failed) || 0;
      const stopped = /остановлен/i.test(String(state.status));
      title = stopped ? 'Загрузка остановлена' : failed ? 'Загрузка завершена с ошибками' : saved ? 'Музыка сохранена' : 'Загрузка завершена';
      description = `Сохранено: ${saved}${failed ? ` · Не удалось: ${failed}. Подробности в журнале.` : saved ? ' · Файлы в папке загрузок.' : ' · Можно запустить загрузку снова.'}`;
      symbol = failed ? '#i-error' : '#i-check';
    } else if (state.basket.length) {
      title = 'Всё готово. Забирайте музыку.';
      description = `${state.basket.length} ${plural(state.basket.length, ['трек', 'трека', 'треков'])} · MP3 · ${state.settings.quality} кбит/с`;
    } else {
      title = 'Ваша музыка ждёт';
      description = 'Добавьте треки в подборку, чтобы скачать их.';
    }
    $('dock-title').textContent = title;
    $('dock-title').title = title;
    $('dock-description').textContent = description;
    $('dock-description').title = description;
    $('dock-status-icon').querySelector('use').setAttribute('href', symbol);
    const announcement = `${state.busy}|${title}`;
    if (announcement !== lastAnnouncement) {
      $('state-announcement').textContent = title;
      lastAnnouncement = announcement;
    }
  }

  function renderLogs() {
    const logs = [...(state.logs || []), ...localLogs];
    const signature = JSON.stringify(logs);
    $('log-indicator').hidden = $('logs-dialog').open || !logs.some(log => /error|critical|exception/i.test(String(log.level)));
    if (signature === logSignature) return;
    logSignature = signature;
    const container = $('logs-content');
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 50;
    const fragment = document.createDocumentFragment();
    if (!logs.length) {
      const empty = document.createElement('p');
      empty.className = 'logs-empty';
      empty.textContent = 'Здесь появятся сообщения о работе приложения.';
      fragment.append(empty);
    }
    for (const log of logs) {
      const entry = document.createElement('div');
      const level = String(log.level || '').toLowerCase();
      entry.className = `log-entry${/error|critical|exception/.test(level) ? ' is-error' : /warn/.test(level) ? ' is-warning' : ''}`;
      const time = document.createElement('span');
      time.className = 'log-time';
      time.textContent = String(log.time ?? '');
      const text = document.createElement('span');
      text.className = 'log-text';
      text.textContent = String(log.text ?? '');
      entry.append(time, text);
      fragment.append(entry);
    }
    container.replaceChildren(fragment);
    if (nearBottom) container.scrollTop = container.scrollHeight;
    $('logs-count').textContent = `${logs.length} ${plural(logs.length, ['событие', 'события', 'событий'])}`;
  }

  function renderControls() {
    const canEdit = idle();
    const searching = state.busy === 'search';
    $('search-input').disabled = !canEdit;
    $('search-submit').disabled = !canEdit || !$('search-input').value.trim();
    $('search-button-text').textContent = searching ? 'Поиск' : 'Найти';
    $('search-button-icon').hidden = searching;
    $('search-spinner').hidden = !searching;
    for (const button of document.querySelectorAll('.source-button')) {
      const active = button.dataset.source === source;
      button.classList.toggle('is-selected', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = !canEdit;
    }
    const selected = new Set(state.basket.map(track => track.url));
    const allSelected = state.results.length > 0 && state.results.every(track => selected.has(track.url));
    $('select-all').textContent = allSelected ? 'Снять выбор' : 'Выбрать все';
    $('select-all').disabled = !canEdit || !state.results.length || Boolean(searchError);
    $('clear-basket').disabled = !canEdit || !state.basket.length;
    $('download-button').disabled = !canEdit || !state.basket.length;
    $('cancel-button').disabled = !connected || pending || state.closing;
    $('empty-action').disabled = !canEdit;
    $('sidebar-folder').disabled = !canEdit || !state.settings.folder;
    $('dock-folder').disabled = $('sidebar-folder').disabled;
    $('connection-dot').classList.toggle('is-connected', connected);
    $('connection-label').textContent = connected ? 'Всё на вашем устройстве' : api() ? 'Нет связи с приложением' : 'Локальное приложение';
    for (const node of [...resultNodes.values(), ...basketNodes.values()]) node.button.disabled = !canEdit;
    const settingsEditable = canEdit && !settingsSaving;
    $('quality-fieldset').disabled = !settingsEditable;
    $('settings-folder').disabled = !settingsEditable;
    $('settings-ascii').disabled = !settingsEditable;
    $('choose-folder').disabled = !settingsEditable;
    $('save-settings').disabled = !settingsEditable;
    $('save-settings').textContent = settingsSaving ? 'Сохраняем…' : 'Сохранить настройки';
    $('settings-busy-notice').hidden = state.busy === 'idle' && !state.closing;
    $('confirm-clear').disabled = !canEdit || !state.basket.length;
    document.body.classList.toggle('is-closing', Boolean(state.closing));
  }

  function render() {
    $('folder-path').textContent = state.settings.folder || 'Укажите в настройках';
    $('sidebar-folder').title = state.settings.folder ? `Открыть папку: ${state.settings.folder}` : 'Укажите папку в настройках';
    renderResults();
    renderBasket();
    renderDock();
    renderLogs();
    renderControls();
  }

  function openSettings() {
    if ($('settings-dialog').open) return;
    const quality = String(state.settings.quality);
    for (const input of document.querySelectorAll('input[name="quality"]')) input.checked = input.value === quality;
    $('settings-folder').value = state.settings.folder || '';
    $('settings-ascii').checked = Boolean(state.settings.ascii_names);
    $('settings-error').hidden = true;
    renderControls();
    $('settings-dialog').showModal();
  }

  async function search() {
    const query = $('search-input').value.trim();
    if (!query || !idle()) return;
    searchError = '';
    searchLogBaseline = (state.logs || []).length;
    $('results-scroll').scrollTop = 0;
    const result = await action('search', [query, sourceName(source)], { search: true });
    if (result.ok) source = normalizeSource(state.settings.source);
    render();
  }

  $('search-form').addEventListener('submit', event => { event.preventDefault(); search(); });
  $('search-input').addEventListener('input', renderControls);
  for (const button of document.querySelectorAll('.source-button')) {
    button.addEventListener('click', () => {
      if (!idle()) return;
      source = button.dataset.source;
      renderControls();
    });
  }
  $('select-all').addEventListener('click', () => {
    const urls = new Set(state.basket.map(track => track.url));
    action('select_all', [!state.results.every(track => urls.has(track.url))]);
  });
  $('clear-basket').addEventListener('click', () => { if (idle() && state.basket.length) $('confirm-dialog').showModal(); });
  $('confirm-clear').addEventListener('click', async () => {
    const result = await action('clear_basket');
    if (result.ok) { $('confirm-dialog').close(); toast('Подборка очищена. Скачанные файлы остались на месте.'); }
  });
  $('download-button').addEventListener('click', () => action('start_download'));
  $('cancel-button').addEventListener('click', async () => {
    const result = await action('cancel_download');
    if (result.ok) toast('Запрошена остановка загрузки. Дождитесь завершения текущего шага.');
  });
  for (const id of ['sidebar-folder', 'dock-folder']) $(id).addEventListener('click', () => action('open_folder'));
  for (const id of ['nav-settings', 'basket-settings']) $(id).addEventListener('click', openSettings);
  $('nav-search').addEventListener('click', () => $('search-input').focus());
  $('empty-action').addEventListener('click', () => {
    if (searchError && $('search-input').value.trim()) search();
    else { $('search-input').focus(); $('search-input').select(); }
  });
  $('nav-logs').addEventListener('click', () => {
    $('logs-dialog').showModal();
    $('log-indicator').hidden = true;
    $('logs-content').scrollTop = $('logs-content').scrollHeight;
  });
  for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => $(button.dataset.close).close());
  for (const dialog of document.querySelectorAll('dialog')) {
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    });
    dialog.addEventListener('cancel', event => {
      if (dialog.id === 'settings-dialog' && settingsSaving) event.preventDefault();
    });
  }
  $('settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!idle() || settingsSaving) return;
    const selectedQuality = document.querySelector('input[name="quality"]:checked');
    const folder = $('settings-folder').value.trim();
    if (!folder || !selectedQuality) {
      $('settings-error').textContent = 'Укажите папку для сохранения и выберите качество.';
      $('settings-error').hidden = false;
      if (!folder) $('settings-folder').focus();
      return;
    }
    settingsSaving = true;
    $('settings-error').hidden = true;
    const result = await action('update_settings', [{ folder, quality: selectedQuality.value, ascii_names: $('settings-ascii').checked }], { settings: true });
    settingsSaving = false;
    renderControls();
    if (result.ok) { $('settings-dialog').close(); toast('Настройки сохранены.'); }
  });
  $('choose-folder').addEventListener('click', async () => {
    const result = await action('choose_folder', [], { settings: true });
    if (result.ok && result.folder != null) $('settings-folder').value = String(result.folder);
  });

  function hidePasteMenu() { $('paste-menu').hidden = true; }
  $('search-input').addEventListener('contextmenu', event => {
    if ($('search-input').disabled) return;
    event.preventDefault();
    const menu = $('paste-menu');
    menu.hidden = false;
    menu.style.left = `${Math.max(8, Math.min(event.clientX, window.innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(event.clientY, window.innerHeight - menu.offsetHeight - 8))}px`;
    $('paste-search').focus();
  });
  async function pasteIntoSearch() {
    hidePasteMenu();
    const input = $('search-input');
    if (input.disabled) return;
    input.focus();
    try {
      if (!navigator.clipboard?.readText) throw new Error('Clipboard unavailable');
      const text = await navigator.clipboard.readText();
      if (input.disabled) return;
      const start = input.selectionStart ?? input.value.length;
      const end = input.selectionEnd ?? start;
      const available = Math.max(0, input.maxLength - (input.value.length - (end - start)));
      input.setRangeText(text.replace(/[\r\n]+/g, ' ').slice(0, available), start, end, 'end');
      renderControls();
    } catch {
      toast('Для вставки нажмите Ctrl+V в поле поиска.');
    }
  }
  $('paste-search').addEventListener('click', pasteIntoSearch);
  document.addEventListener('pointerdown', event => { if (!$('paste-menu').contains(event.target)) hidePasteMenu(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !$('paste-menu').hidden) { hidePasteMenu(); $('search-input').focus(); }
    if ((event.ctrlKey || event.metaKey) && event.code === 'KeyF' && !document.querySelector('dialog[open]')) {
      event.preventDefault();
      $('search-input').focus();
      $('search-input').select();
    }
    // Keep native paste, including Ctrl+V on Russian keyboard layouts.
  });
  for (const type of ['dragover', 'drop']) {
    document.addEventListener(type, event => {
      const types = Array.from(event.dataTransfer?.types || []);
      const editable = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement;
      if (types.includes('Files') || types.includes('text/uri-list') || !editable) event.preventDefault();
    });
  }
  window.addEventListener('resize', hidePasteMenu);
  window.addEventListener('blur', hidePasteMenu);

  async function initializeBridge() {
    if (!api() || initializing) return;
    initializing = true;
    await refreshState(true);
    if (!pollTimer) pollTimer = window.setInterval(() => { if (!fetching && !pending) refreshState(); }, 350);
    initializing = false;
  }
  window.addEventListener('pywebviewready', initializeBridge);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && api()) refreshState(); });
  render();
  if (api()) initializeBridge();
  else window.setTimeout(() => {
    if (api()) initializeBridge();
    else {
      $('bridge-message').textContent = 'Запустите через start.bat, чтобы искать и скачивать музыку.';
      $('bridge-banner').hidden = false;
    }
  }, 500);
})();

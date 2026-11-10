I18n.apply(document);
/* Themed custom select menus synchronized with underlying native select elements. */
(() => {
  let opened = null;
  const controls = new Map();
  const close = () => {
    if (!opened) return;
    opened.panel.hidden = true;
    opened.button.setAttribute('aria-expanded', 'false');
    opened = null;
  };
  const labelFor = (select) => select.getAttribute('aria-label') ||
    document.querySelector(`label[for="${select.id}"]`)?.textContent?.trim() ||
    select.closest('label')?.firstChild?.textContent?.trim() || I18n.t("Выбор");
  const sync = (select) => {
    const control = controls.get(select);
    if (!control) return;
    control.value.textContent = select.selectedOptions[0]?.textContent || I18n.t("Выберите");
    if (opened === control) control.render();
  };
  window.syncSiteSelect = (id) => sync(document.getElementById(id));
  document.querySelectorAll('select:not(.hidden)').forEach((select) => {
    const wrap = document.createElement('div');
    wrap.className = 'site-select';
    select.before(wrap);
    wrap.append(select);
    select.classList.add('site-select-native');
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'site-select-button';
    button.setAttribute('role', 'combobox');
    button.setAttribute('aria-label', labelFor(select));
    button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    const value = document.createElement('span');
    value.className = 'site-select-value';
    button.append(value);
    const chevron = document.createElement('span');
    chevron.className = 'mi site-select-chevron';
    chevron.setAttribute('aria-hidden', 'true');
    chevron.textContent = 'expand_more';
    button.append(chevron);
    const panel = document.createElement('div');
    panel.className = 'site-select-panel';
    panel.hidden = true;
    const search = document.createElement('input');
    search.className = 'site-select-search';
    search.type = 'search';
    search.placeholder = I18n.t("Поиск в списке");
    search.setAttribute('aria-label', I18n.t("Поиск в списке"));
    const list = document.createElement('div');
    list.className = 'site-select-options';
    list.setAttribute('role', 'listbox');
    panel.append(search, list);
    wrap.append(button, panel);
    const control = { button, panel, value, render: () => {
      const options = [...select.options];
      const filter = search.value.trim().toLocaleLowerCase(I18n.language);
      const matches = options.filter((option) => option.textContent.toLocaleLowerCase(I18n.language).includes(filter));
      list.replaceChildren();
      for (const option of matches.slice(0, 80)) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'site-select-option';
        item.setAttribute('role', 'option');
        item.setAttribute('aria-selected', String(option.value === select.value));
        item.disabled = option.disabled;
        const text = document.createElement('span');
        text.textContent = option.textContent;
        item.append(text);
        if (option.value === select.value) {
          const check = document.createElement('span');
          check.className = 'mi';
          check.setAttribute('aria-hidden', 'true');
          check.textContent = 'check';
          item.append(check);
        }
        item.addEventListener('click', () => {
          select.value = option.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          sync(select);
          close();
          button.focus();
        });
        list.append(item);
      }
      if (!matches.length) { const empty = document.createElement('p'); empty.className = 'site-select-empty'; empty.textContent = I18n.t("Ничего не найдено"); list.append(empty); }
      search.hidden = options.length < 12;
    }};
    controls.set(select, control);
    button.addEventListener('click', () => {
      if (opened === control) { close(); return; }
      close();
      search.value = '';
      control.render();
      panel.hidden = false;
      button.setAttribute('aria-expanded', 'true');
      opened = control;
      if (!search.hidden) search.focus();
    });
    button.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        if (opened !== control) button.click();
        list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
      }
    });
    search.addEventListener('input', control.render);
    panel.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.preventDefault(); close(); button.focus(); }
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const options = [...list.querySelectorAll('.site-select-option:not(:disabled)')];
        if (!options.length) return;
        const index = options.indexOf(document.activeElement);
        options[(index + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length].focus();
      }
    });
    select.addEventListener('change', () => sync(select));
    new MutationObserver(() => sync(select)).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['selected', 'disabled'] });
    sync(select);
  });
  document.addEventListener('pointerdown', (event) => { if (opened && !opened.button.parentElement.contains(event.target)) close(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
})();

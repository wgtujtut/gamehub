'use strict';
// GameHub — фронтенд панели. Ванильный JS, без сборки и внешних библиотек.
// Данные с сервера (названия игр, описания раздач) вставляются только как текст:
// через textContent / createElement. innerHTML — только для своих статичных SVG-иконок.

/* ================= DOM-помощники ================= */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const SVG_NS = 'http://www.w3.org/2000/svg';

// Добавить детей: строки и числа становятся текстовыми узлами
function addKids(node, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : String(kid));
  }
}

function setStyle(node, style) {
  for (const [k, v] of Object.entries(style)) {
    if (k.startsWith('--')) node.style.setProperty(k, v);
    else node.style[k] = v;
  }
}

// HTML-элемент. props: class, style (объект), data (объект), on<событие>, остальное — атрибуты
function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'style') setStyle(node, v);
    else if (k === 'data') Object.assign(node.dataset, v);
    else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  addKids(node, kids);
  return node;
}

// SVG-элемент: text — содержимое, data — dataset, остальное — атрибуты
function sv(tag, props, ...kids) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null) continue;
    if (k === 'text') node.textContent = v;
    else if (k === 'data') Object.assign(node.dataset, v);
    else node.setAttribute(k, v);
  }
  addKids(node, kids);
  return node;
}

const empty = text => h('div', {class: 'empty'}, text);
const loading = (text = 'Загрузка…') => h('div', {class: 'loading'}, h('span', {class: 'spinner'}), text);

function debounce(fn, ms) {
  let t = null;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

// Кнопка «занята» на время действия: блокируем и меняем подпись в <span>
async function busy(btn, text, fn) {
  const span = btn.querySelector('span');
  const old = span ? span.textContent : '';
  btn.disabled = true;
  if (span) span.textContent = text;
  try { return await fn(); } finally {
    btn.disabled = false;
    if (span) span.textContent = old;
  }
}

/* ================= Иконки (статичные шаблоны) ================= */

const ICONS = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5a.8.8 0 0 0-1.2.7z"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.5h7.5A2.5 2.5 0 0 1 21 10v7.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/></svg>',
  dots: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.9"/><circle cx="12" cy="12" r="1.9"/><circle cx="19" cy="12" r="1.9"/></svg>',
  flame: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c4.2 0 7-2.8 7-6.9 0-3-1.7-5.4-3.4-7.2-.4 1.7-1.3 2.9-2.5 3.5.4-3.6-1.4-6.9-4.1-8.9.2 3.1-1.6 5.2-3.2 7C4.6 11.3 5 13 5 15.1 5 19.2 7.8 22 12 22z"/></svg>',
  trophy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5.5A2.5 2.5 0 0 0 8 10.5M16 6h2.5A2.5 2.5 0 0 1 16 10.5M12 13v4M8.5 20h7M10 17h4"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13.5 2 4 13.5h6.5L9.5 22 20 9.5h-6.6z"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>',
  hourglass: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12M6 21h12M7 3c0 5 5 5 5 9s-5 4-5 9M17 3c0 5-5 5-5 9s5 4 5 9"/></svg>',
};

function icon(name, cls = '') {
  const span = document.createElement('span');
  span.className = 'ico ' + cls;
  span.innerHTML = ICONS[name];  // статичная строка из ICONS, данных тут нет
  return span;
}

/* ================= Форматирование ================= */

const MONTHS = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTHS_LABEL = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const WEEKDAYS_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

const nf0 = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 0});
const nf1 = new Intl.NumberFormat('ru-RU', {minimumFractionDigits: 1, maximumFractionDigits: 1});
const nf2 = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2});
const pad2 = n => String(n).padStart(2, '0');

// plural(5, 'день', 'дня', 'дней') → 'дней'
function plural(n, one, few, many) {
  const a = Math.abs(Math.trunc(n)) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

// Секунды → [['2', 'ч'], ['05', 'мин']]
function durParts(sec) {
  const m = Math.floor(Math.max(0, sec || 0) / 60);
  if (m < 60) return [[String(m), 'мин']];
  return [[nf0.format(Math.floor(m / 60)), 'ч'], [pad2(m % 60), 'мин']];
}

// «2 ч 05 мин», «45 мин», «0 мин»
function fmtDur(sec) {
  return durParts(sec).map(p => p.join(' ')).join(' ');
}

// Живой таймер: «1:23:45»
function fmtClock(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(sec / 3600)}:${pad2(Math.floor(sec % 3600 / 60))}:${pad2(sec % 60)}`;
}

// «12,4 ГБ»
function fmtBytes(b) {
  b = Math.max(0, b || 0);
  const units = [['ТБ', 2 ** 40], ['ГБ', 2 ** 30], ['МБ', 2 ** 20], ['КБ', 2 ** 10]];
  for (const [unit, k] of units) {
    if (b >= k) {
      const v = b / k;
      return `${(v >= 100 ? nf0 : nf1).format(v)} ${unit}`;
    }
  }
  return `${b} Б`;
}

const fmtNum = n => nf0.format(n || 0);
const fmtMs = v => (v == null ? '—' : nf0.format(Math.round(v)));
const fmtMs1 = v => (v == null ? '—' : nf1.format(v));
const fmtPct = v => (v == null ? '—' : `${v ? nf1.format(v) : 0}%`);

const parseDay = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const toDate = x => (x instanceof Date ? x : typeof x === 'string' ? parseDay(x) : new Date(x * 1000));
const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const weekdayMon = d => (d.getDay() + 6) % 7;  // пн = 0
const daysBetween = (a, b) => Math.round((startOfDay(b) - startOfDay(a)) / 86400000);

// «14 мар» (год — если не текущий). Принимает ts, Date или 'YYYY-MM-DD'
function fmtDate(x, withYear) {
  const d = toDate(x);
  let s = `${d.getDate()} ${MONTHS[d.getMonth()]}`;
  if (withYear ?? d.getFullYear() !== new Date().getFullYear()) s += ` ${d.getFullYear()}`;
  return s;
}

function fmtTime(ts, withSec = false) {
  const d = toDate(ts);
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}` + (withSec ? `:${pad2(d.getSeconds())}` : '');
}

// Последний запуск: «сегодня», «вчера», «3 дня назад», «14 мар»
function fmtAgo(ts) {
  if (!ts) return 'не запускалась';
  const n = daysBetween(new Date(ts * 1000), new Date());
  if (n <= 0) return 'сегодня';
  if (n === 1) return 'вчера';
  if (n < 7) return `${n} ${plural(n, 'день', 'дня', 'дней')} назад`;
  return fmtDate(ts);
}

// Свежесть данных: «только что», «5 мин назад», «3 ч назад»
function fmtSince(ts) {
  if (!ts) return 'ещё не загружались';
  const s = Date.now() / 1000 - ts;
  if (s < 60) return 'только что';
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return fmtAgo(ts);
}

// «осталось 1 д 5 ч»
function fmtLeft(ts) {
  const s = ts - Date.now() / 1000;
  if (s <= 0) return 'закончилась';
  const d = Math.floor(s / 86400), hh = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return `осталось ${d} д ${hh} ч`;
  if (hh) return `осталось ${hh} ч ${m} мин`;
  return `осталось ${Math.max(1, m)} мин`;
}

// Подходящий шаг сетки графика: не больше maxTicks делений
function niceStep(max, steps, maxTicks = 5) {
  for (const s of steps) if (max / s <= maxTicks) return s;
  const last = steps[steps.length - 1];
  return last * Math.ceil(max / (last * maxTicks));
}

const lastOf = g => Math.max(g.last || 0, g.last_played || 0);

/* ================= API ================= */

// Ключ доступа к API: окно открывает панель с ?t=<ключ>. Запоминаем его на сессию и убираем из адреса.
const TOKEN = (() => {
  const fromUrl = new URLSearchParams(location.search).get('t');
  if (fromUrl) {
    try { sessionStorage.setItem('gh-token', fromUrl); } catch { /* хранилище недоступно */ }
    history.replaceState(null, '', location.pathname + location.hash);
    return fromUrl;
  }
  try { return sessionStorage.getItem('gh-token') || ''; } catch { return ''; }
})();

const POST_HEADERS = {'Content-Type': 'application/json'};
let offline = false;
let retryTimer = null;

async function request(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {cache: 'no-store', ...opts, headers: {'X-GameHub': TOKEN, ...(opts.headers || {})}});
  } catch {
    setOffline(true);
    const err = new Error('Нет связи с GameHub');
    err.offline = true;
    throw err;
  }
  setOffline(false);
  let data = null;
  try { data = await res.json(); } catch { /* не JSON */ }
  if (res.status === 403) throw new Error('Нет доступа: открой GameHub заново через ярлык или трей');
  if (!res.ok) throw new Error((data && data.error) || `Ошибка сервера (${res.status})`);
  if (data == null) throw new Error('Сервер прислал непонятный ответ');
  return data;
}

const apiGet = path => request(path);
const apiPost = (path, body = {}) => request(path, {method: 'POST', headers: POST_HEADERS, body: JSON.stringify(body)});

// Ошибка → тост (если сервер просто недоступен — уже висит баннер)
function fail(e) {
  if (e && e.offline) return;
  console.error(e);
  toast((e && e.message) || 'Что-то пошло не так', 'error');
}

// Баннер «GameHub не запущен» и переподключение
function setOffline(value) {
  if (value === offline) return;
  offline = value;
  $('#offline').hidden = !value;
  $('#srv-dot').className = 'dot ' + (value ? 'bad' : 'good');
  if (value) {
    retryTimer = setInterval(() => request('/api/state').catch(() => {}), 5000);
  } else {
    clearInterval(retryTimer);
    retryTimer = null;
    route();  // сервер вернулся — перезагрузить текущую вкладку
  }
}

let cfgCache = null;
async function getConfig() {
  if (!cfgCache) cfgCache = await apiGet('/api/config');
  return cfgCache;
}

/* ================= Тосты и подсказка ================= */

function toast(msg, kind = 'info') {
  const box = $('#toasts');
  // одинаковое сообщение уже на экране — не дублируем
  if ([...box.children].some(t => t.textContent === msg && t.classList.contains('show'))) return;
  while (box.children.length >= 4) box.firstChild.remove();
  const t = h('div', {class: `toast ${kind}`, role: 'status'}, msg);
  box.append(t);
  requestAnimationFrame(() => t.classList.add('show'));
  setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => t.remove(), 300);
  }, kind === 'error' ? 6000 : 3500);
}

// Подсказка для любого элемента с data-tip (текст — через textContent)
function initTooltip() {
  const tip = $('#tip');
  let target = null;
  const hide = () => { tip.hidden = true; target = null; };
  document.addEventListener('mouseover', e => {
    const t = e.target.closest ? e.target.closest('[data-tip]') : null;
    if (t === target) return;
    target = t;
    if (!t) { tip.hidden = true; return; }
    tip.textContent = t.dataset.tip;
    tip.hidden = false;
  });
  document.addEventListener('mousemove', e => {
    if (tip.hidden) return;
    if (target && !target.isConnected) { hide(); return; }
    const pad = 14, w = tip.offsetWidth, hgt = tip.offsetHeight;
    let x = e.clientX + pad, y = e.clientY + pad;
    if (x + w > innerWidth - 8) x = e.clientX - w - pad;
    if (y + hgt > innerHeight - 8) y = e.clientY - hgt - pad;
    tip.style.transform = `translate(${Math.max(4, x)}px, ${Math.max(4, y)}px)`;
  });
  document.documentElement.addEventListener('mouseleave', hide);
  window.addEventListener('scroll', hide, {passive: true});
}

/* ================= Обложки ================= */

const coverUrl = (id, kind) => `/cover/${encodeURIComponent(id)}?kind=${kind}`;

function hueOf(str) {
  let x = 0;
  for (const c of String(str)) x = (x * 31 + c.codePointAt(0)) >>> 0;
  return x % 360;
}

const firstLetter = name => ([...String(name || '').trim()][0] || '?').toUpperCase();

// Обложка: под картинкой всегда заглушка (градиент + буква), картинка закрывает её после загрузки.
// Для не-Steam игр сервер отдаёт 404, поэтому картинку даже не запрашиваем.
function coverBox(game, kind, cls = '') {
  const id = String(game.game_id || game.id || '');  // game_id первым: у сессий id — номер сессии
  const box = h('div', {class: `cover ${cls}`, style: {'--h': hueOf(game.name || id)}},
    h('span', {class: 'cover-ph'}, firstLetter(game.name)));
  if (id.startsWith('steam:')) {
    const img = h('img', {alt: '', loading: 'lazy', decoding: 'async', src: coverUrl(id, kind)});
    img.addEventListener('load', () => box.classList.add('loaded'));
    img.addEventListener('error', () => img.remove());
    box.append(img);
  }
  return box;
}

// Ссылка из интернета: только http/https
function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
}

/* ================= Общие действия ================= */

async function launchGame(g) {
  try {
    await apiPost('/api/launch', {game_id: g.id || g.game_id});
    toast(`Запускаю: ${g.name}`, 'ok');
  } catch (e) { fail(e); }
}

async function openFolder(g) {
  try { await apiPost('/api/open_folder', {game_id: g.id}); } catch (e) { fail(e); }
}

async function uninstallGame(g) {
  try {
    await apiPost('/api/uninstall', {game_id: g.id});
    toast('Steam спросит подтверждение', 'ok');
  } catch (e) { fail(e); }
}

/* ================= Обновления ================= */

let updateHidden = '';
async function checkUpdate() {
  try {
    const info = await apiGet('/api/update');
    $('#srv-addr').textContent = 'GameHub ' + info.current;
    const u = info.update;
    const bar = $('#update-bar');
    if (!u || updateHidden === u.version) { bar.hidden = true; return; }
    $('#update-text').textContent = `Вышла версия ${u.version}`;
    $('#update-go').hidden = !info.installed;
    bar.hidden = false;
    bar.dataset.page = u.page || '';
    bar.dataset.version = u.version;
  } catch { /* нет связи — баннер «не запущен» уже показан */ }
}

async function installUpdate(e) {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = 'Скачиваю…';
  try {
    await apiPost('/api/update/install');
    toast('Обновление скачивается — GameHub перезапустится сам', 'ok');
  } catch (err) {
    fail(err);
    btn.disabled = false;
    btn.textContent = 'Обновить';
  }
}

async function openUrl(url) {
  try {
    await apiPost('/api/open_url', {url});
    toast('Открываю в браузере', 'ok');
  } catch (e) { fail(e); }
}

// Блок «Давно не играл» (библиотека и чистка)
function staleBlock(stale, days) {
  const games = (stale && stale.games) || [];
  if (!games.length) return null;
  const n = games.length;
  const title = days ? `Давно не играл (${days} ${plural(days, 'день', 'дня', 'дней')}) — можно освободить` : 'Давно не играл — можно освободить';
  const list = h('div', {class: 'stale-list'}, games.map(g => {
    const appid = String(g.id || '').startsWith('steam:') ? String(g.id).slice(6) : '';
    const action = /^\d+$/.test(appid)
      ? h('button', {class: 'btn sm danger', type: 'button', title: 'Steam сам спросит подтверждение', onclick: () => uninstallGame(g)}, 'Удалить через Steam')
      : h('span', {class: 'muted small'}, 'удалить вручную');
    return h('div', {class: 'stale-row'},
      coverBox(g, 'header', 'cover-header'),
      h('div', {class: 'stale-name'},
        h('div', {title: g.name}, g.name),
        h('div', {class: 'muted small'}, g.last ? `последний запуск: ${fmtAgo(g.last)}` : 'ни разу не запускалась')),
      h('span', {class: 'stale-size'}, fmtBytes(g.size_bytes)),
      action);
  }));
  return h('details', {class: 'stale card'},
    h('summary', {},
      icon('hourglass'),
      h('span', {}, title),
      h('b', {class: 'accent'}, fmtBytes(stale.bytes)),
      h('span', {class: 'muted'}, `· ${n} ${plural(n, 'игра', 'игры', 'игр')}`),
      icon('chev', 'chev')),
    list);
}

function renderStale(box, stale, days) {
  box.replaceChildren();
  const block = staleBlock(stale, days);
  if (block) box.append(block);
}

// Цвет индикатора пинга
function pingLevel(p) {
  if (!p || !p.count) return '';
  if (p.last == null || p.loss > 2) return 'bad';
  if (p.last < 40) return 'good';
  if (p.last < 80) return 'mid';
  return 'bad';
}

// Сегментный переключатель
function bindSeg(sel, onChange) {
  const box = $(sel);
  box.addEventListener('click', e => {
    const btn = e.target.closest('button[data-v]');
    if (!btn || btn.classList.contains('on')) return;
    for (const b of box.children) b.classList.toggle('on', b === btn);
    onChange(btn.dataset.v);
  });
}

/* ================= Тепловая карта ================= */

function heatLevel(sec) {
  const m = (sec || 0) / 60;
  if (m < 1) return 0;
  if (m < 30) return 1;
  if (m < 60) return 2;
  if (m < 120) return 3;
  if (m < 240) return 4;
  return 5;
}

// Последние N недель: первая колонка начинается с понедельника, последняя — сегодня
function lastWeeks(heat, weeks) {
  if (!heat || !heat.length) return [];
  const last = parseDay(heat[heat.length - 1].date);
  return heat.slice(-((weeks - 1) * 7 + weekdayMon(last) + 1));
}

// Сетка квадратиков: колонки — недели, строки — дни (пн сверху)
function heatmapNode(days, labeled) {
  const grid = h('div', {class: 'heat' + (labeled ? ' labeled' : '')});
  if (!days.length) return grid;
  const offset = weekdayMon(parseDay(days[0].date));
  const cols = Math.ceil((days.length + offset) / 7);
  const shift = labeled ? 1 : 0;  // колонка дней недели и строка месяцев
  grid.style.setProperty('--cols', cols);

  if (labeled) {
    WEEKDAYS.forEach((w, i) => {
      if (i % 2 === 0) grid.append(h('span', {class: 'heat-wd', style: {gridColumn: 1, gridRow: i + 2}}, w));
    });
  }
  const months = [];
  let prevMonth = -1;
  days.forEach((d, i) => {
    const idx = i + offset, col = Math.floor(idx / 7), row = idx % 7;
    const date = parseDay(d.date);
    const text = `${fmtDate(date)} — ${d.seconds > 0 ? fmtDur(d.seconds) : 'не играл'}`;
    grid.append(h('span', {
      class: 'hc l' + heatLevel(d.seconds),
      style: {gridColumn: col + 1 + shift, gridRow: row + 1 + shift},
      data: {tip: text},
    }));
    // подпись месяца — над первой неделей, где он начинается
    if ((row === 0 || i === 0) && date.getMonth() !== prevMonth) {
      prevMonth = date.getMonth();
      months.push({col, month: prevMonth});
    }
  });
  if (labeled) {
    months.forEach((m, i) => {
      const next = months[i + 1];
      if (next && next.col - m.col < 3) return;  // слишком близко к следующей — пропускаем
      const span = Math.min(3, cols - m.col);  // не вылезать за последнюю колонку
      grid.append(h('span', {class: 'heat-m', style: {gridColumn: `${m.col + 2} / span ${span}`, gridRow: 1}}, MONTHS_LABEL[m.month]));
    });
  }
  return grid;
}

function heatLegend() {
  return h('div', {class: 'heat-legend'}, 'меньше', [0, 1, 2, 3, 4, 5].map(l => h('span', {class: 'hc l' + l})), 'больше');
}

/* ================= Роутинг ================= */

const TITLES = {home: 'Главная', library: 'Библиотека', stats: 'Статистика', deals: 'Халява', clean: 'Чистка', net: 'Сеть', settings: 'Настройки'};
let currentView = null;
const timers = [];

// Таймер, который живёт только пока открыта вкладка
function every(fn, ms) { timers.push(setInterval(fn, ms)); }

function route() {
  let name = location.hash.slice(1);
  if (!Object.hasOwn(VIEWS, name)) name = 'home';
  while (timers.length) clearInterval(timers.pop());
  currentView = name;
  for (const sec of $$('.view')) sec.hidden = sec.id !== 'view-' + name;
  for (const a of $$('.nav a')) a.classList.toggle('active', a.dataset.view === name);
  document.title = `${TITLES[name]} — GameHub`;
  closeMenus();
  VIEWS[name].enter();
}

/* ================= Главная ================= */

const home = {offset: 0, playKey: null, topKey: null, topRefs: [], gm: null, busy: false};

const TILES = [
  ['today', 'Сегодня', 'dur'],
  ['week', 'За неделю', 'dur'],
  ['month', 'За 30 дней', 'dur'],
  ['total', 'Всего', 'dur'],
  ['streak', 'Серия дней', 'days', 'flame'],
  ['best_streak', 'Лучшая серия', 'days', 'trophy'],
  ['avg_day_month', 'Средне в день', 'dur'],
];

function homeEnter() {
  const d = new Date().toLocaleDateString('ru-RU', {weekday: 'long', day: 'numeric', month: 'long'});
  $('#home-date').textContent = d.charAt(0).toUpperCase() + d.slice(1);
  homePoll();
  loadHomeHeat();
  every(homePoll, 2000);
  every(homeTick, 1000);
  every(loadHomeHeat, 60000);
}

async function homePoll() {
  if (document.hidden || home.busy) return;
  home.busy = true;
  try {
    const st = await apiGet('/api/state');
    home.offset = (st.now || Date.now() / 1000) - Date.now() / 1000;  // разница часов сервера и браузера
    renderHome(st);
    // сервер нашёл обновление позже, чем открылась панель — показать плашку сразу, а не через полчаса
    if (st.update && $('#update-bar').dataset.version !== st.update.version) checkUpdate();
  } catch (e) { fail(e); } finally { home.busy = false; }
}

function renderHome(st) {
  const sum = st.summary || {};
  renderPlaying(st);
  renderTiles(sum);
  renderLimit(st.limit);
  renderTopWeek(sum.top_week);
  renderDisks(st.disks);
  renderHomePing(st.ping);
  $('#deals-count').textContent = st.deals_now ?? '—';
  renderGamemode(st.gamemode);
  homeTick();
}

// Живой таймер текущей игры
function homeTick() {
  const now = Date.now() / 1000 + home.offset;
  for (const t of $$('.now-timer')) t.textContent = fmtClock(now - Number(t.dataset.start));
}

function gmBadge(gm) {
  const on = gm && gm.active;
  return h('span', {class: 'badge' + (on ? ' accent' : '')}, icon('bolt'), on ? 'Режим игры' : 'Режим игры выкл');
}

// Блок «Сейчас играешь». Перестраиваем только когда сменилась игра — иначе мигает картинка
function renderPlaying(st) {
  const box = $('#now-playing');
  const playing = st.playing || [];
  const key = playing.map(p => p.game_id).join('|') + '#' + (st.gamemode && st.gamemode.active ? 1 : 0);
  if (key === home.playKey) return;
  home.playKey = key;

  if (!playing.length) {
    box.className = 'now card idle';
    box.replaceChildren(h('div', {class: 'now-idle'},
      h('div', {class: 'now-label muted'}, 'Сейчас ничего не запущено'),
      h('div', {class: 'now-title'}, 'Во что сыграем?'),
      h('div', {class: 'recent', id: 'home-recent'}, loading())));
    loadRecent();
    return;
  }

  const p = playing[0];
  box.className = 'now card active';
  box.replaceChildren(
    coverBox(p, 'hero', 'now-bg'),
    h('div', {class: 'now-shade'}),
    h('div', {class: 'now-body'},
      h('div', {class: 'now-label'}, h('span', {class: 'live-dot'}), 'Сейчас играешь'),
      h('div', {class: 'now-title'}, p.name),
      h('div', {class: 'now-meta'},
        h('span', {class: 'now-timer', data: {start: p.start}}, fmtClock(p.elapsed)),
        gmBadge(st.gamemode)),
      playing.length > 1 ? h('div', {class: 'now-more'}, 'Ещё запущено: ' + playing.slice(1).map(x => x.name).join(', ')) : null));
}

// 5 последних игр, когда ничего не запущено
async function loadRecent() {
  try {
    const data = await apiGet('/api/library');
    const box = $('#home-recent');
    if (!box) return;
    const list = (data.games || [])
      .filter(g => !g.not_game && lastOf(g) > 0)
      .sort((a, b) => lastOf(b) - lastOf(a))
      .slice(0, 5);
    if (!list.length) {
      box.replaceChildren(h('div', {class: 'muted'}, 'Пока нет истории запусков — загляни в библиотеку.'));
      return;
    }
    box.replaceChildren(...list.map(g => h('div', {class: 'recent-item'},
      coverBox(g, 'header', 'cover-wide'),
      h('div', {class: 'recent-name', title: g.name}, g.name),
      h('div', {class: 'recent-foot'},
        h('span', {class: 'muted small'}, fmtAgo(lastOf(g))),
        h('button', {class: 'btn primary sm', type: 'button', disabled: !g.launch, onclick: () => launchGame(g)}, icon('play'), 'Играть')))));
  } catch (e) {
    fail(e);
    const box = $('#home-recent');
    if (box) box.replaceChildren();
  }
}

function durNode(sec) {
  const node = h('div', {class: 'val'});
  for (const [num, unit] of durParts(sec)) node.append(h('b', {}, num), h('i', {}, unit));
  return node;
}

function daysNode(n) {
  n = n || 0;
  return h('div', {class: 'val'}, h('b', {}, String(n)), h('i', {}, plural(n, 'день', 'дня', 'дней')));
}

function renderTiles(sum) {
  $('#home-tiles').replaceChildren(...TILES.map(([key, label, type, ic]) =>
    h('div', {class: 'tile card' + (key === 'streak' && sum[key] > 0 ? ' hot' : '')},
      h('div', {class: 'card-label'}, ic ? icon(ic) : null, label),
      type === 'dur' ? durNode(sum[key]) : daysNode(sum[key]))));
}

function renderLimit(lim) {
  const box = $('#home-limit');
  if (!lim || !(lim.daily_minutes > 0)) { box.hidden = true; return; }
  box.hidden = false;
  const today = lim.today_minutes || 0, max = lim.daily_minutes;
  const frac = today / max;
  const over = frac >= 1;
  box.replaceChildren(
    h('div', {class: 'limit-head'},
      h('span', {class: 'card-label'}, 'Лимит на сегодня'),
      h('span', {class: 'num'}, `${fmtDur(today * 60)} из ${fmtDur(max * 60)}`),
      over ? h('span', {class: 'badge red'}, 'превышен') : h('span', {class: 'muted small'}, `осталось ${fmtDur((max - today) * 60)}`)),
    h('div', {class: 'bar' + (over ? ' over' : frac >= 0.8 ? ' warn' : '')},
      h('span', {style: {width: Math.min(100, frac * 100) + '%'}})));
}

// Топ недели: строки перестраиваем только при смене состава, иначе обновляем цифры
function renderTopWeek(list) {
  const box = $('#home-top');
  list = list || [];
  const key = list.map(g => g.game_id).join('|');
  if (key !== home.topKey) {
    home.topKey = key;
    home.topRefs = [];
    if (!list.length) { box.replaceChildren(empty('За неделю ещё не играл')); return; }
    box.replaceChildren(...list.map((g, i) => {
      const time = h('span', {class: 'top-time'});
      const fill = h('span');
      home.topRefs.push({time, fill});
      return h('div', {class: 'top-row'},
        h('span', {class: 'top-rank'}, String(i + 1)),
        coverBox(g, 'header', 'cover-header'),
        h('div', {class: 'top-main'},
          h('div', {class: 'top-line'}, h('span', {class: 'top-name', title: g.name}, g.name), time),
          h('div', {class: 'bar thin'}, fill)));
    }));
  }
  const max = (list[0] && list[0].seconds) || 1;
  list.forEach((g, i) => {
    const ref = home.topRefs[i];
    ref.time.textContent = fmtDur(g.seconds);
    ref.fill.style.width = (g.seconds / max * 100) + '%';
  });
}

function renderDisks(disks) {
  const box = $('#home-disks');
  if (!disks || !disks.length) { box.replaceChildren(empty('Нет данных о дисках')); return; }
  box.replaceChildren(...disks.map(d => {
    const used = d.total ? 1 - d.free / d.total : 0;
    const low = d.total > 0 && d.free / d.total < 0.1;
    return h('div', {class: 'disk' + (low ? ' low' : '')},
      h('div', {class: 'disk-head'},
        h('span', {class: 'disk-name'}, d.name),
        h('span', {class: 'small muted'}, `свободно ${fmtBytes(d.free)} из ${fmtBytes(d.total)}`)),
      h('div', {class: 'bar'}, h('span', {style: {width: used * 100 + '%'}})));
  }));
}

function renderHomePing(ping) {
  const box = $('#home-ping');
  const names = Object.keys(ping || {});
  if (!names.length) { box.replaceChildren(empty('Нет данных о пинге')); return; }
  box.replaceChildren(...names.map(name => {
    const p = ping[name] || {};
    return h('div', {class: 'pr'},
      h('span', {class: 'dot ' + pingLevel(p)}),
      h('span', {class: 'pr-name'}, name),
      h('span', {class: 'muted small'}, `ср. ${fmtMs(p.avg)} мс · потери ${fmtPct(p.loss)}`),
      h('span', {class: 'pr-ms'}, fmtMs(p.last), h('i', {}, 'мс')));
  }));
}

function renderGamemode(gm) {
  if (!gm) return;
  home.gm = gm;
  $('#gm-card').classList.toggle('on', !!gm.active);
  $('#gm-state').textContent = gm.active ? 'Включён' : 'Выключен';
  const scheme = gm.scheme ? `План питания: ${gm.scheme}` : 'План питания неизвестен';
  $('#gm-scheme').textContent = scheme + (gm.auto ? ' · авто при запуске игры' : '');
  $('#gm-toggle span').textContent = gm.active ? 'Выключить' : 'Включить';
}

async function toggleGamemode() {
  const btn = $('#gm-toggle');
  btn.disabled = true;
  try {
    const r = await apiPost('/api/gamemode', {action: home.gm && home.gm.active ? 'off' : 'on'});
    renderGamemode(r.gamemode);
    home.playKey = null;  // обновить бейдж в баннере
    toast(r.gamemode && r.gamemode.active ? 'Режим игры включён' : 'Режим игры выключен', 'ok');
    if (r.killed && r.killed.length) toast('Закрыто: ' + r.killed.join(', '));
  } catch (e) { fail(e); } finally { btn.disabled = false; }
}

async function loadHomeHeat() {
  if (document.hidden) return;
  try {
    const st = await apiGet('/api/stats?days=30');
    $('#home-heat').replaceChildren(heatmapNode(lastWeeks(st.heatmap, 20), false));
  } catch (e) { fail(e); }
}

/* ================= Библиотека ================= */

const lib = {data: null, cards: new Map(), source: 'all', sort: 'recent', q: '', showNot: false, staleDays: null};
const SRC_NAMES = {steam: 'Steam', epic: 'Epic', custom: 'Своя'};

function libraryEnter() { loadLibrary(); }

async function loadLibrary(rescan = false) {
  if (!lib.data) $('#lib-grid').replaceChildren(loading('Загружаю библиотеку…'));
  try {
    const [data, cfg] = await Promise.all([
      rescan ? apiPost('/api/library/rescan') : apiGet('/api/library'),
      getConfig().catch(() => null),
    ]);
    lib.data = data;
    lib.staleDays = cfg ? cfg.stale_days : null;
    lib.cards = new Map((data.games || []).map(g => [g.id, libCard(g)]));
    renderLibGrid();
    renderStale($('#lib-stale'), data.stale, lib.staleDays);
    if (rescan) toast(`Готово, игр найдено: ${(data.games || []).length}`, 'ok');
  } catch (e) {
    fail(e);
    if (!lib.data) $('#lib-grid').replaceChildren(empty('Не удалось загрузить библиотеку'));
  }
}

function libCard(g) {
  const menu = h('div', {class: 'menu', hidden: true},
    h('button', {type: 'button', onclick: () => setNotGame(g, !g.not_game)}, g.not_game ? 'Это игра' : 'Это не игра'));
  const more = h('button', {
    class: 'btn sm icon-only', type: 'button', title: 'Ещё', 'aria-label': 'Ещё',
    onclick: e => { e.stopPropagation(); toggleMenu(menu); },
  }, icon('dots'));

  const cover = coverBox(g, 'portrait', 'cover-portrait');
  cover.append(h('div', {class: 'gcard-actions'},
    h('button', {
      class: 'btn primary sm', type: 'button', disabled: !g.launch,
      title: g.launch ? null : 'Не указан способ запуска', onclick: () => launchGame(g),
    }, icon('play'), 'Играть'),
    h('button', {class: 'btn sm', type: 'button', onclick: () => openFolder(g)}, icon('folder'), 'Папка'),
    h('div', {class: 'menu-wrap'}, more, menu)));
  if (g.not_game) cover.append(h('span', {class: 'badge corner'}, 'не игра'));

  return h('div', {class: 'gcard' + (g.not_game ? ' notgame' : '')},
    cover,
    h('div', {class: 'gcard-info'},
      h('div', {class: 'gcard-name', title: g.name}, g.name),
      h('div', {class: 'gcard-meta'},
        h('span', {}, g.seconds > 0 ? fmtDur(g.seconds) : '—'),
        h('span', {}, fmtAgo(lastOf(g)))),
      h('div', {class: 'gcard-meta'},
        h('span', {}, g.size_bytes ? fmtBytes(g.size_bytes) : '—'),
        h('span', {class: 'src'}, SRC_NAMES[g.source] || g.source || ''))));
}

const byName = (a, b) => String(a.name).localeCompare(String(b.name), 'ru', {sensitivity: 'base'});
const LIB_SORT = {
  recent: (a, b) => lastOf(b) - lastOf(a) || byName(a, b),
  played: (a, b) => (b.seconds || 0) - (a.seconds || 0) || byName(a, b),
  size: (a, b) => (b.size_bytes || 0) - (a.size_bytes || 0) || byName(a, b),
  alpha: byName,
};

function renderLibGrid() {
  const grid = $('#lib-grid');
  const games = (lib.data && lib.data.games) || [];
  const q = lib.q.trim().toLocaleLowerCase('ru');
  const visible = games.filter(g => lib.showNot || !g.not_game);
  const list = visible.filter(g => {
    if (lib.source === 'custom' ? g.source === 'steam' || g.source === 'epic' : lib.source !== 'all' && g.source !== lib.source) return false;
    return !q || String(g.name).toLocaleLowerCase('ru').includes(q);
  }).sort(LIB_SORT[lib.sort]);

  grid.replaceChildren(...list.map(g => lib.cards.get(g.id)));
  if (!list.length) {
    grid.append(empty(games.length ? 'Ничего не найдено' : 'Игры не найдены. Нажми «Пересканировать» или добавь свои в настройках.'));
  }
  const size = list.reduce((s, g) => s + (g.size_bytes || 0), 0);
  $('#lib-count').textContent = `Показано ${list.length} из ${visible.length} · ${fmtBytes(size)} на дисках`;
}

function toggleMenu(menu) {
  const open = menu.hidden;
  closeMenus();
  if (!open) return;
  menu.hidden = false;
  const card = menu.closest('.gcard');
  if (card) card.classList.add('menu-open');
}

function closeMenus() {
  for (const m of $$('.menu:not([hidden])')) {
    m.hidden = true;
    const card = m.closest('.gcard');
    if (card) card.classList.remove('menu-open');
  }
}

async function setNotGame(g, value) {
  closeMenus();
  try {
    await apiPost('/api/library/not_game', {game_id: g.id, value});
    toast(value ? `«${g.name}» больше не считается игрой` : `«${g.name}» снова в играх`, 'ok');
    await loadLibrary();
  } catch (e) { fail(e); }
}

/* ================= Статистика ================= */

const stats = {days: 30, data: null, top: []};
// 6 различимых цветов на тёмном фоне + серый для «Других»
const PALETTE = ['#c6ff3d', '#4cc9ff', '#ff5fa2', '#ffb020', '#9d7bff', '#2ee6c5'];
const OTHER_COLOR = '#4a505a';

function statsEnter() { loadStats(); }

async function loadStats() {
  const days = stats.days;
  const view = $('#view-stats');
  if (!stats.data) $('#st-chart').replaceChildren(loading());
  view.classList.add('is-loading');
  try {
    const d = await apiGet(`/api/stats?days=${days}`);
    if (days !== stats.days) return;  // пока грузили, переключили период
    stats.data = d;
    renderStats();
  } catch (e) { fail(e); } finally { view.classList.remove('is-loading'); }
}

function renderStats() {
  const d = stats.data;
  const pg = d.per_game || [];
  stats.top = pg.slice(0, 6).map(g => g.game_id);
  const total = pg.reduce((s, g) => s + (g.seconds || 0), 0);
  const sessions = pg.reduce((s, g) => s + (g.sessions || 0), 0);
  const n = stats.days;
  $('#st-sub').textContent = `За ${n} ${plural(n, 'день', 'дня', 'дней')}: ${fmtDur(total)} · в среднем ${fmtDur(total / n)} в день · ${sessions} ${plural(sessions, 'сессия', 'сессии', 'сессий')}`;

  const legend = pg.slice(0, 6).map((g, i) => legendItem(PALETTE[i], g.name));
  if (pg.length > 6) legend.push(legendItem(OTHER_COLOR, 'Другие'));
  $('#st-legend').replaceChildren(...legend);

  renderStatsChart();
  renderStatsGames(pg, total);
  renderStatsWhen(d);
  renderStatsHeat(d.heatmap);
  renderStatsSessions(d.sessions);
}

function legendItem(color, name) {
  return h('span', {class: 'lg'}, h('i', {style: {background: color}}), h('span', {class: 'lg-name'}, name));
}

function fmtAxisHours(v) {
  if (v === 0) return '0';
  return v < 1 ? `${Math.round(v * 60)} мин` : `${nf2.format(v)} ч`;
}

// Подсказка столбика: дата, всего, разбивка по играм
function dayTip(day, names) {
  const lines = [fmtDate(day.date) + ', ' + WEEKDAYS_FULL[weekdayMon(parseDay(day.date))].toLowerCase(), `Всего: ${fmtDur(day.seconds)}`];
  const games = Object.entries(day.games || {}).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]);
  for (const [id, sec] of games.slice(0, 8)) lines.push(`${(names && names[id]) || id}: ${fmtDur(sec)}`);
  if (games.length > 8) lines.push(`и ещё ${games.length - 8}`);
  return lines.join('\n');
}

// Столбики по дням, стопкой по играм (SVG)
function renderStatsChart() {
  const d = stats.data, box = $('#st-chart');
  if (!d || !box.clientWidth) return;
  const days = d.days || [];
  const W = box.clientWidth, H = 280, L = 56, R = 8, T = 12, B = 28;
  const pw = W - L - R, ph = H - T - B;
  const maxH = Math.max(0, ...days.map(x => x.seconds || 0)) / 3600;
  const step = niceStep(maxH, [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12]);
  const top = Math.max(step, Math.ceil(maxH / step - 1e-9) * step);
  const svg = sv('svg', {class: 'chart-svg', width: W, height: H, viewBox: `0 0 ${W} ${H}`});

  for (let v = 0; v <= top + 1e-9; v += step) {
    const y = T + ph - v / top * ph;
    svg.append(
      sv('line', {class: 'grid', x1: L, x2: W - R, y1: y, y2: y}),
      sv('text', {class: 'axis', x: L - 8, y: y + 4, 'text-anchor': 'end', text: fmtAxisHours(v)}));
  }

  const n = days.length || 1, slot = pw / n, bw = Math.max(1, Math.min(slot * 0.7, 34));
  const labelEvery = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(pw / 60))));
  days.forEach((day, i) => {
    const x = L + i * slot, bx = x + (slot - bw) / 2;
    const g = sv('g', {class: 'bar-g', data: {tip: dayTip(day, d.names)}});
    g.append(sv('rect', {class: 'hit', x, y: T, width: slot, height: ph}));
    const parts = stats.top.map((id, k) => [(day.games && day.games[id]) || 0, PALETTE[k]]);
    const known = parts.reduce((s, p) => s + p[0], 0);
    parts.push([Math.max(0, (day.seconds || 0) - known), OTHER_COLOR]);
    let y = T + ph;
    for (const [sec, color] of parts) {
      if (sec < 1) continue;
      const hgt = sec / 3600 / top * ph;
      y -= hgt;
      g.append(sv('rect', {x: bx, y, width: bw, height: Math.max(hgt, 1), fill: color}));
    }
    svg.append(g);
    if ((n - 1 - i) % labelEvery === 0) {
      svg.append(sv('text', {class: 'axis', x: x + slot / 2, y: H - 8, 'text-anchor': 'middle', text: fmtDate(day.date, false)}));
    }
  });
  box.replaceChildren(svg);
}

function renderStatsGames(pg, total) {
  const box = $('#st-games');
  if (!pg.length) { box.replaceChildren(empty('За этот период игр не было')); return; }
  const head = h('thead', {}, h('tr', {},
    h('th', {}, 'Игра'), h('th', {class: 'r'}, 'Время'), h('th', {class: 'r'}, 'Сессий'),
    h('th', {class: 'r'}, 'Средняя'), h('th', {class: 'r'}, 'Доля')));
  const rows = pg.map((g, i) => {
    const share = total ? g.seconds / total * 100 : 0;
    return h('tr', {},
      h('td', {}, h('div', {class: 'gname'},
        coverBox(g, 'header', 'cover-mini'),
        h('span', {class: 'swatch', style: {background: i < 6 ? PALETTE[i] : OTHER_COLOR}}),
        h('span', {class: 'ellipsis', title: g.name}, g.name))),
      h('td', {class: 'r strong'}, fmtDur(g.seconds)),
      h('td', {class: 'r'}, String(g.sessions || 0)),
      h('td', {class: 'r muted'}, g.sessions ? fmtDur(g.seconds / g.sessions) : '—'),
      h('td', {class: 'r'}, h('div', {class: 'share'},
        h('div', {class: 'bar thin'}, h('span', {style: {width: share + '%'}})),
        h('span', {}, nf1.format(share) + '%'))));
  });
  box.replaceChildren(h('table', {class: 'tbl'}, head, h('tbody', {}, rows)));
}

// Простые столбики из div: по часам и по дням недели
function barsNode(values, labels, tips) {
  const max = Math.max(...values, 1);
  const peak = values.indexOf(Math.max(...values));
  return h('div', {class: 'mini-bars'}, values.map((v, i) =>
    h('div', {class: 'mb' + (i === peak && v > 0 ? ' peak' : ''), data: {tip: `${tips[i]} — ${fmtDur(v)}`}},
      h('div', {class: 'mb-col'}, h('span', {class: 'mb-fill', style: {height: (v / max * 100) + '%'}})),
      h('span', {class: 'mb-label'}, labels[i]))));
}

function renderStatsWhen(d) {
  const hours = d.by_hour && d.by_hour.length === 24 ? d.by_hour : Array(24).fill(0);
  const wd = d.by_weekday && d.by_weekday.length === 7 ? d.by_weekday : Array(7).fill(0);
  $('#st-when').replaceChildren(
    h('div', {class: 'when-block'},
      h('div', {class: 'card-label'}, 'По часам суток'),
      barsNode(hours, hours.map((_, i) => (i % 3 === 0 ? String(i) : '')), hours.map((_, i) => `${pad2(i)}:00–${pad2((i + 1) % 24)}:00`))),
    h('div', {class: 'when-block'},
      h('div', {class: 'card-label'}, 'По дням недели'),
      barsNode(wd, WEEKDAYS, WEEKDAYS_FULL)));
}

function renderStatsHeat(heat) {
  const days = lastWeeks(heat || [], 53);
  const total = days.reduce((s, d) => s + (d.seconds || 0), 0);
  const active = days.filter(d => d.seconds > 0).length;
  $('#st-year-total').textContent = `${fmtDur(total)} · ${active} ${plural(active, 'день', 'дня', 'дней')} с игрой`;
  $('#st-heat').replaceChildren(heatmapNode(days, true), heatLegend());
}

function renderStatsSessions(list) {
  const box = $('#st-sessions');
  if (!list || !list.length) { box.replaceChildren(empty('Сессий пока нет')); return; }
  const head = h('thead', {}, h('tr', {},
    h('th', {}, 'Игра'), h('th', {}, 'Начало'), h('th', {class: 'r'}, 'Длительность'),
    h('th', {class: 'r'}, 'Пинг'), h('th', {class: 'r'}, 'Потери')));
  const rows = list.map(s => {
    const dur = Math.max(0, (s.end || s.start) - s.start);
    return h('tr', {},
      h('td', {}, h('div', {class: 'gname'}, coverBox(s, 'header', 'cover-mini'), h('span', {class: 'ellipsis', title: s.name}, s.name))),
      h('td', {class: 'muted'}, `${fmtDate(s.start)}, ${fmtTime(s.start)}`),
      h('td', {class: 'r strong'}, s.open ? h('span', {class: 'live'}, h('span', {class: 'live-dot'}), fmtDur(dur)) : fmtDur(dur)),
      h('td', {class: 'r'}, s.ping_avg != null ? `${fmtMs(s.ping_avg)} мс` : '—'),
      h('td', {class: 'r'}, s.ping_loss != null ? fmtPct(s.ping_loss) : '—'));
  });
  box.replaceChildren(h('table', {class: 'tbl'}, head, h('tbody', {}, rows)));
}

/* ================= Халява ================= */

const deals = {data: null};

function dealsEnter() {
  loadDeals();
  every(updateDealsSub, 30000);
}

async function loadDeals(refresh = false) {
  if (!deals.data) $('#deals-now').replaceChildren(loading('Загружаю раздачи…'));
  try {
    deals.data = await (refresh ? apiPost('/api/deals/refresh') : apiGet('/api/deals'));
    renderDeals();
    if (refresh) toast('Раздачи обновлены', 'ok');
  } catch (e) {
    fail(e);
    if (!deals.data) $('#deals-now').replaceChildren(empty('Не удалось загрузить раздачи'));
  }
}

function updateDealsSub() {
  if (!deals.data) return;
  const ts = deals.data.fetched_at;
  $('#deals-sub').textContent = ts ? 'Обновлено ' + fmtSince(ts) : 'Раздачи ещё не загружались';
}

function renderDeals() {
  const d = deals.data;
  updateDealsSub();
  const errBox = $('#deals-errors');
  errBox.hidden = !(d.errors && d.errors.length);
  errBox.textContent = d.errors && d.errors.length ? 'Не удалось загрузить: ' + d.errors.join('; ') : '';

  // забранные — в конец (sort стабильный, порядок сервера сохраняется)
  const now = [...(d.now || [])].sort((a, b) => Number(!!a.claimed) - Number(!!b.claimed));
  const left = now.filter(x => !x.claimed).length;
  $('#deals-now-count').textContent = now.length ? String(left) : '';
  $('#deals-now').replaceChildren(...(now.length ? now.map(x => dealCard(x, false)) : [empty('Сейчас бесплатных раздач нет')]));

  const up = d.upcoming || [];
  $('#deals-up-count').textContent = up.length ? String(up.length) : '';
  $('#deals-upcoming').replaceChildren(...(up.length ? up.map(x => dealCard(x, true)) : [empty('Анонсов пока нет')]));
}

function storeClass(store) {
  const s = String(store || '').toLowerCase();
  if (s.includes('epic')) return 'epic';
  if (s.includes('steam')) return 'steam';
  if (s.includes('gog')) return 'gog';
  return 'other';
}

function dealCard(x, upcoming) {
  const media = h('div', {class: 'deal-media', style: {'--h': hueOf(x.title)}}, h('span', {class: 'cover-ph'}, firstLetter(x.title)));
  const img = safeUrl(x.image);
  if (img) {
    const im = h('img', {alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer', src: img});
    im.addEventListener('load', () => media.classList.add('loaded'));
    im.addEventListener('error', () => im.remove());
    media.append(im);
  }
  media.append(h('span', {class: 'store ' + storeClass(x.store)}, x.store || 'Магазин'));

  let when;
  if (upcoming) when = x.start ? `с ${fmtDate(x.start)}, ${fmtTime(x.start)}` : 'дата неизвестна';
  else when = x.end ? fmtLeft(x.end) : 'срок не указан';

  const url = safeUrl(x.url);
  const body = h('div', {class: 'deal-body'},
    h('div', {class: 'deal-title'}, x.title),
    h('div', {class: 'deal-meta'},
      x.worth ? h('s', {class: 'worth'}, x.worth) : null,
      h('span', {class: 'free'}, upcoming ? 'Скоро' : 'Бесплатно'),
      h('span', {class: 'muted small'}, when)),
    x.description ? h('p', {class: 'deal-desc', title: x.description}, x.description) : null,
    h('div', {class: 'deal-actions'},
      h('button', {class: upcoming ? 'btn sm' : 'btn primary sm', type: 'button', disabled: !url, onclick: () => openUrl(url)}, upcoming ? 'Открыть страницу' : 'Забрать'),
      upcoming ? null : claimSwitch(x)));
  return h('article', {class: 'deal card' + (x.claimed ? ' claimed' : '')}, media, body);
}

function claimSwitch(x) {
  const input = h('input', {type: 'checkbox'});
  input.checked = !!x.claimed;
  input.addEventListener('change', async () => {
    input.disabled = true;
    try {
      await apiPost('/api/deals/claim', {key: x.key, claimed: input.checked});
      x.claimed = input.checked;
      renderDeals();
    } catch (e) {
      input.checked = !input.checked;
      input.disabled = false;
      fail(e);
    }
  });
  return h('label', {class: 'switch-line'}, h('span', {class: 'switch'}, input, h('span', {class: 'slider'})), 'Уже забрал');
}

/* ================= Чистка ================= */

const clean = {data: null, sel: null, busy: false};

function cleanEnter() { loadCleaner(); }

async function loadCleaner() {
  $('#clean-list').replaceChildren(
    loading('Считаю размер кэшей… это может занять несколько секунд'),
    ...[1, 2, 3, 4].map(() => h('div', {class: 'skel'})));
  $('#clean-total').textContent = 'считаю…';
  $('#clean-go').disabled = true;
  try {
    const [data, cfg] = await Promise.all([apiGet('/api/cleaner'), getConfig().catch(() => null)]);
    clean.data = data;
    const targets = data.targets || [];
    const ids = new Set(targets.map(t => t.id));
    // выбор сохраняется между пересчётами, при первом заходе — по умолчанию
    clean.sel = clean.sel
      ? new Set([...clean.sel].filter(id => ids.has(id)))
      : new Set(targets.filter(t => t.default).map(t => t.id));
    renderCleaner();
    renderStale($('#clean-stale'), data.stale, cfg ? cfg.stale_days : null);
  } catch (e) {
    fail(e);
    $('#clean-list').replaceChildren(empty('Не удалось посчитать. Попробуй «Пересчитать».'));
    $('#clean-total').textContent = '—';
  }
}

function renderCleaner() {
  const targets = (clean.data && clean.data.targets) || [];
  const list = $('#clean-list');
  if (!targets.length) { list.replaceChildren(empty('Чистить нечего')); updateCleanTotal(); return; }
  list.replaceChildren(...targets.map(t => {
    const cb = h('input', {type: 'checkbox', class: 'cb'});
    cb.checked = clean.sel.has(t.id);
    cb.addEventListener('change', () => {
      if (cb.checked) clean.sel.add(t.id);
      else clean.sel.delete(t.id);
      updateCleanTotal();
    });
    const paths = t.paths || [];
    return h('label', {class: 'clean-row' + (t.bytes ? '' : ' zero')},
      cb,
      h('div', {class: 'clean-info'},
        h('div', {class: 'clean-name'}, t.name),
        t.note ? h('div', {class: 'note'}, t.note) : null,
        h('div', {class: 'paths', title: paths.join('\n')}, paths.join('  ·  '))),
      h('div', {class: 'clean-files'}, `${fmtNum(t.files)} ${plural(t.files || 0, 'файл', 'файла', 'файлов')}`),
      h('div', {class: 'clean-size'}, fmtBytes(t.bytes)));
  }));
  updateCleanTotal();
}

function selectedTargets() {
  return ((clean.data && clean.data.targets) || []).filter(t => clean.sel && clean.sel.has(t.id));
}

function updateCleanTotal() {
  const sel = selectedTargets();
  const bytes = sel.reduce((s, t) => s + (t.bytes || 0), 0);
  $('#clean-total').textContent = '~' + fmtBytes(bytes);
  $('#clean-go').disabled = clean.busy || !sel.length;
}

async function doClean() {
  const sel = selectedTargets();
  if (!sel.length || clean.busy) return;
  const bytes = sel.reduce((s, t) => s + (t.bytes || 0), 0);
  const ok = confirm(`Очистить выбранное?\n\n${sel.map(t => '• ' + t.name).join('\n')}\n\nБудет освобождено ~${fmtBytes(bytes)}. Занятые файлы будут пропущены.`);
  if (!ok) return;
  clean.busy = true;
  const btn = $('#clean-go');
  try {
    await busy(btn, 'Чищу…', async () => {
      const r = await apiPost('/api/cleaner/clean', {ids: sel.map(t => t.id)});
      renderCleanResult(r);
      toast(`Освобождено ${fmtBytes(r.freed)}`, 'ok');
    });
  } catch (e) { fail(e); }
  clean.busy = false;
  loadCleaner();
}

function renderCleanResult(r) {
  const results = r.results || [];
  const deleted = results.reduce((s, x) => s + (x.deleted || 0), 0);
  const skipped = results.reduce((s, x) => s + (x.skipped || 0), 0);
  $('#clean-result').replaceChildren(h('div', {class: 'card result'},
    h('div', {class: 'result-head'},
      h('span', {class: 'card-label'}, 'Готово'),
      h('b', {class: 'result-big'}, 'Освобождено ' + fmtBytes(r.freed)),
      h('span', {class: 'muted'}, `удалено ${fmtNum(deleted)} ${plural(deleted, 'файл', 'файла', 'файлов')}`
        + (skipped ? ` · пропущено занятых: ${fmtNum(skipped)}` : ''))),
    h('div', {class: 'result-list'}, results.map(x => h('div', {class: 'result-row'},
      h('span', {}, x.name),
      h('span', {class: 'num'}, fmtBytes(x.freed)),
      h('span', {class: 'muted small'}, x.skipped ? `пропущено: ${fmtNum(x.skipped)}` : '')))),
    skipped ? h('p', {class: 'result-hint'}, 'Занятые файлы держат запущенные программы — закрой их и повтори.') : null));
}

/* ================= Сеть ================= */

const net = {minutes: 30, data: null, busy: false};
const netColor = i => PALETTE[i % PALETTE.length];

function netEnter() {
  loadPing();
  every(loadPing, 5000);
}

async function loadPing() {
  if (document.hidden || net.busy) return;
  net.busy = true;
  const minutes = net.minutes;
  try {
    const d = await apiGet(`/api/ping?minutes=${minutes}`);
    if (minutes !== net.minutes) return;
    net.data = d;
    renderNet();
  } catch (e) { fail(e); } finally { net.busy = false; }
}

function netNames(d) {
  if (d.targets && d.targets.length) return d.targets.map(t => t.name);
  return Object.keys(d.stats || {});
}

function renderNet() {
  const names = netNames(net.data);
  $('#net-legend').replaceChildren(...names.map((n, i) => legendItem(netColor(i), n)));
  renderNetChart();
  renderNetCards();
}

// Линии пинга по целям; пропуски (null) — красные засечки под графиком
function renderNetChart() {
  const d = net.data, box = $('#net-chart');
  if (!d || !box.clientWidth) return;
  const names = netNames(d);
  const W = box.clientWidth, H = 300, L = 56, R = 12, T = 12, B = 42;
  const pw = W - L - R, ph = H - T - B;
  const t1 = Date.now() / 1000, t0 = t1 - net.minutes * 60;
  const series = (d.series || []).filter(p => p.ts >= t0 - 1);

  let maxV = 0;
  for (const p of series) for (const n of names) {
    const v = p.values && p.values[n];
    if (v != null && v > maxV) maxV = v;
  }
  const base = Math.max(maxV, 20);
  const step = niceStep(base, [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]);
  const top = Math.ceil(base / step) * step;
  const X = ts => L + (ts - t0) / (t1 - t0) * pw;
  const Y = v => T + ph - Math.min(v, top) / top * ph;
  const svg = sv('svg', {class: 'chart-svg', width: W, height: H, viewBox: `0 0 ${W} ${H}`});

  for (let v = 0; v <= top + 1e-9; v += step) {
    const y = Y(v);
    svg.append(
      sv('line', {class: 'grid', x1: L, x2: W - R, y1: y, y2: y}),
      sv('text', {class: 'axis', x: L - 8, y: y + 4, 'text-anchor': 'end', text: v ? `${v} мс` : '0'}));
  }
  const stepMin = [1, 2, 5, 10, 15].find(m => net.minutes / m <= 6) || 15;
  for (let t = Math.ceil(t0 / (stepMin * 60)) * stepMin * 60; t <= t1; t += stepMin * 60) {
    const x = X(t);
    svg.append(
      sv('line', {class: 'grid v', x1: x, x2: x, y1: T, y2: T + ph}),
      sv('text', {class: 'axis', x, y: H - 6, 'text-anchor': 'middle', text: fmtTime(t)}));
  }

  // засечки потерь
  const lossY = T + ph + 8;
  svg.append(sv('line', {class: 'loss-base', x1: L, x2: W - R, y1: lossY + 4, y2: lossY + 4}));
  for (const p of series) {
    const lost = names.filter(n => p.values && n in p.values && p.values[n] == null);
    if (!lost.length) continue;
    const x = X(p.ts);
    svg.append(sv('line', {class: 'loss-tick', x1: x, x2: x, y1: lossY, y2: lossY + 8, data: {tip: `${fmtTime(p.ts, true)} — нет ответа: ${lost.join(', ')}`}}));
  }

  names.forEach((n, i) => {
    let path = '', pen = false;
    for (const p of series) {
      const v = p.values && p.values[n];
      if (v == null) { pen = false; continue; }
      path += `${pen ? 'L' : 'M'}${X(p.ts).toFixed(1)} ${Y(v).toFixed(1)}`;
      pen = true;
    }
    if (path) svg.append(sv('path', {class: 'line', d: path, stroke: netColor(i)}));
  });

  box.replaceChildren(svg);
  if (!series.length) box.append(h('div', {class: 'muted small'}, 'Замеров пока нет — подожди несколько секунд.'));
}

function renderNetCards() {
  const d = net.data;
  const names = netNames(d);
  const targets = Object.fromEntries((d.targets || []).map(t => [t.name, t]));
  if (!names.length) { $('#net-cards').replaceChildren(empty('Цели пинга не заданы — добавь их в настройках.')); return; }
  $('#net-cards').replaceChildren(...names.map((n, i) => {
    const s = (d.stats && d.stats[n]) || {};
    const t = targets[n];
    const cells = [
      ['Средний', fmtMs(s.avg)], ['Мин', fmtMs(s.min)], ['Макс', fmtMs(s.max)],
      ['Джиттер', fmtMs1(s.jitter)], ['Потери', fmtPct(s.loss)],
    ];
    return h('div', {class: 'card ping-card', style: {'--c': netColor(i)}},
      h('div', {class: 'ping-head'},
        h('span', {class: 'dot ' + pingLevel(s)}),
        h('b', {}, n),
        t ? h('span', {class: 'ping-host'}, `${t.host}:${t.port}`) : null),
      h('div', {class: 'ping-big'}, h('b', {}, fmtMs(s.last)), h('i', {}, 'мс')),
      h('div', {class: 'ping-stats'}, cells.map(([k, v]) => h('div', {}, h('span', {}, k), h('b', {}, v)))));
  }));
}

/* ================= Настройки ================= */

const settings = {cfg: null};

async function settingsEnter() {
  try {
    const cfg = await apiGet('/api/config');
    settings.cfg = cfg;
    cfgCache = cfg;
    fillSettings(cfg);
  } catch (e) { fail(e); }
}

function fillSettings(cfg) {
  const gm = cfg.gamemode || {}, dl = cfg.deals || {};
  $('#set-gm-auto').checked = !!gm.auto;
  $('#set-gm-power').checked = !!gm.power_plan;
  $('#set-gm-kill').checked = !!gm.kill_on_start;
  $('#set-gm-list').value = (gm.kill_list || []).join('\n');
  $('#set-deals-enabled').checked = !!dl.enabled;
  $('#set-deals-notify').checked = !!dl.notify;
  $('#set-deals-interval').value = dl.interval_hours ?? 3;
  $('#set-limit').value = (cfg.limits && cfg.limits.daily_minutes) ?? 0;
  $('#set-notify-end').checked = !!cfg.notify_session_end;
  $('#set-stale').value = cfg.stale_days ?? 60;
  $('#set-ping-list').replaceChildren(...((cfg.ping && cfg.ping.targets) || []).map(pingRow));
  $('#set-games-list').replaceChildren(...(cfg.extra_games || []).map(gameRow));
}

function pingRow(t = {}) {
  const row = h('div', {class: 'ed-row ed-ping'},
    h('input', {class: 'input', name: 'name', placeholder: 'Название', value: t.name ?? ''}),
    h('input', {class: 'input', name: 'host', placeholder: '1.1.1.1 или host.com', value: t.host ?? '', spellcheck: 'false'}),
    h('input', {class: 'input', name: 'port', type: 'number', min: 1, max: 65535, placeholder: '443', value: t.port ?? 443}),
    h('button', {class: 'btn ghost', type: 'button', title: 'Удалить', 'aria-label': 'Удалить', onclick: () => row.remove()}, icon('x')));
  return row;
}

function gameRow(g = {}) {
  const row = h('div', {class: 'ed-row ed-game'},
    h('input', {class: 'input', name: 'name', placeholder: 'Escape from Tarkov', value: g.name ?? ''}),
    h('input', {class: 'input', name: 'dir', placeholder: 'D:\\Games\\EscapeFromTarkov', value: g.dir ?? '', spellcheck: 'false'}),
    h('input', {class: 'input', name: 'launch', placeholder: 'C:\\...\\Launcher.exe', value: g.launch ?? '', spellcheck: 'false'}),
    h('button', {class: 'btn ghost', type: 'button', title: 'Удалить', 'aria-label': 'Удалить', onclick: () => row.remove()}, icon('x')));
  row.orig = g;  // исходная запись — чтобы сохранить id и прочие поля
  return row;
}

const fieldVal = (row, name) => row.querySelector(`[name="${name}"]`).value.trim();

const TRANSLIT = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e', ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm',
  н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u', ф: 'f', х: 'h', ц: 'c', ч: 'ch', ш: 'sh', щ: 'sch',
  ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

function slugify(name) {
  const s = [...name.toLowerCase()].map(c => TRANSLIT[c] ?? c).join('')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return s || 'game';
}

function readPingRows() {
  const list = [], seen = new Set();
  for (const row of $$('#set-ping-list .ed-row')) {
    const name = fieldVal(row, 'name'), host = fieldVal(row, 'host'), portRaw = fieldVal(row, 'port');
    if (!name && !host) continue;
    if (!name || !host) throw new Error('Пинг: у каждой цели нужны название и адрес');
    const port = portRaw === '' ? 443 : Number(portRaw);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error(`Пинг «${name}»: порт — число от 1 до 65535`);
    if (seen.has(name)) throw new Error(`Пинг: название «${name}» повторяется`);
    seen.add(name);
    list.push({name, host, port});
  }
  return list;
}

function readGameRows() {
  const rows = $$('#set-games-list .ed-row');
  const used = new Set(rows.map(r => r.orig && r.orig.id).filter(Boolean));
  const list = [];
  for (const row of rows) {
    const name = fieldVal(row, 'name'), dir = fieldVal(row, 'dir'), launch = fieldVal(row, 'launch');
    if (!name && !dir && !launch) continue;
    if (!name || !dir) throw new Error('Свои игры: нужны название и папка');
    let id = row.orig && row.orig.id;
    if (!id) {
      const base = 'custom:' + slugify(name);
      id = base;
      for (let k = 2; used.has(id); k++) id = `${base}-${k}`;
      used.add(id);
    }
    list.push({...row.orig, id, name, dir, launch});
  }
  return list;
}

function readInt(sel, min, max, label) {
  const raw = $(sel).value.trim();
  const v = Number(raw);
  if (raw === '' || !Number.isInteger(v) || v < min || v > max) throw new Error(`${label}: целое число от ${min} до ${max}`);
  return v;
}

// Собрать разделы конфига из формы (ошибка ввода — исключение с понятным текстом)
function readSettings() {
  const cfg = settings.cfg;
  return {
    gamemode: {
      ...cfg.gamemode,
      auto: $('#set-gm-auto').checked,
      power_plan: $('#set-gm-power').checked,
      kill_on_start: $('#set-gm-kill').checked,
      kill_list: $('#set-gm-list').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean),
    },
    deals: {
      ...cfg.deals,
      enabled: $('#set-deals-enabled').checked,
      notify: $('#set-deals-notify').checked,
      interval_hours: readInt('#set-deals-interval', 1, 168, 'Интервал проверки раздач'),
    },
    limits: {...cfg.limits, daily_minutes: readInt('#set-limit', 0, 1440, 'Лимит в день')},
    notify_session_end: $('#set-notify-end').checked,
    stale_days: readInt('#set-stale', 1, 3650, '«Давно не играл»'),
    ping: {...cfg.ping, targets: readPingRows()},
    extra_games: readGameRows(),
  };
}

async function saveSettings() {
  if (!settings.cfg) return;
  let next;
  try { next = readSettings(); } catch (e) { toast(e.message, 'error'); return; }
  // отправляем только изменённые разделы, каждый целиком
  const changed = {};
  for (const [k, v] of Object.entries(next)) {
    if (JSON.stringify(v) !== JSON.stringify(settings.cfg[k])) changed[k] = v;
  }
  if (!Object.keys(changed).length) { toast('Изменений нет'); return; }
  try {
    await busy($('#set-save'), 'Сохраняю…', async () => {
      const cfg = await apiPost('/api/config', changed);
      settings.cfg = cfg;
      cfgCache = cfg;
      fillSettings(cfg);
    });
    toast('Сохранено', 'ok');
  } catch (e) { fail(e); }
}

async function killNow() {
  const out = $('#set-kill-result');
  try {
    await busy($('#set-kill-now'), 'Закрываю…', async () => {
      const r = await apiPost('/api/gamemode', {action: 'kill'});
      const killed = r.killed || [];
      out.textContent = killed.length ? 'Закрыто: ' + killed.join(', ') : 'Ничего из списка не запущено';
    });
  } catch (e) { fail(e); }
}

/* ================= Запуск ================= */

const VIEWS = {
  home: {enter: homeEnter, poll: homePoll},
  library: {enter: libraryEnter},
  stats: {enter: statsEnter},
  deals: {enter: dealsEnter},
  clean: {enter: cleanEnter},
  net: {enter: netEnter, poll: loadPing},
  settings: {enter: settingsEnter},
};

function init() {
  // Обновления: при старте и раз в полчаса
  $('#update-go').addEventListener('click', installUpdate);
  $('#update-notes').addEventListener('click', () => { const page = $('#update-bar').dataset.page; if (page) openUrl(page); });
  $('#update-hide').addEventListener('click', () => { updateHidden = $('#update-bar').dataset.version; $('#update-bar').hidden = true; });
  checkUpdate();
  setInterval(checkUpdate, 10 * 60 * 1000);

  // Главная
  $('#gm-toggle').addEventListener('click', toggleGamemode);

  // Библиотека
  $('#lib-search').addEventListener('input', e => { lib.q = e.target.value; renderLibGrid(); });
  $('#lib-sort').addEventListener('change', e => { lib.sort = e.target.value; renderLibGrid(); });
  $('#lib-notgames').addEventListener('change', e => { lib.showNot = e.target.checked; renderLibGrid(); });
  bindSeg('#lib-source', v => { lib.source = v; renderLibGrid(); });
  $('#lib-rescan').addEventListener('click', e => busy(e.currentTarget, 'Сканирую…', () => loadLibrary(true)));

  // Статистика
  bindSeg('#st-range', v => { stats.days = Number(v); loadStats(); });

  // Халява
  $('#deals-refresh').addEventListener('click', e => busy(e.currentTarget, 'Обновляю…', () => loadDeals(true)));

  // Чистка
  $('#clean-go').addEventListener('click', doClean);
  $('#clean-reload').addEventListener('click', e => busy(e.currentTarget, 'Считаю…', loadCleaner));

  // Сеть
  bindSeg('#net-range', v => { net.minutes = Number(v); net.busy = false; loadPing(); });

  // Настройки
  $('#set-form').addEventListener('submit', e => e.preventDefault());
  $('#set-save').addEventListener('click', saveSettings);
  $('#set-kill-now').addEventListener('click', killNow);
  $('#set-ping-add').addEventListener('click', () => {
    const row = pingRow();
    $('#set-ping-list').append(row);
    row.querySelector('input').focus();
  });
  $('#set-games-add').addEventListener('click', () => {
    const row = gameRow();
    $('#set-games-list').append(row);
    row.querySelector('input').focus();
  });

  // Общее
  initTooltip();
  document.addEventListener('click', closeMenus);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenus(); });
  window.addEventListener('resize', debounce(() => {
    if (currentView === 'stats') renderStatsChart();
    if (currentView === 'net') renderNetChart();
  }, 150));
  document.addEventListener('visibilitychange', () => {
    const v = VIEWS[currentView];
    if (!document.hidden && v && v.poll) v.poll();
  });
  window.addEventListener('hashchange', route);
  route();
}

init();

const CONFIG = JSON.parse(document.getElementById('report-config').textContent);

const SETS = CONFIG.sets;
const TAB_CATEGORIES = CONFIG.categories;
const TIME_OPTIONS = CONFIG.time_options || ['Щойно', 'Менше години тому', 'Вибрати дату і час'];
const CITIES = CONFIG.cities || [];
const DISTRICTS = CONFIG.districts || [];

const form           = document.getElementById('report-form');
const opts           = document.getElementById('opts');
const bTime          = document.getElementById('block-time');
const optsTime       = document.getElementById('opts-time');
const errTime        = document.getElementById('err-time');
const timePickerWrap = document.getElementById('time-picker-wrap');
const exactDate      = document.getElementById('exact-date');
const exactTime      = document.getElementById('exact-time');
const pickerDate     = document.getElementById('picker-date');
const pickerTime     = document.getElementById('picker-time');
const tabs           = [...document.querySelectorAll('.seg button')];
const segSlider      = document.getElementById('seg-slider');
const city           = document.getElementById('city');
const labelCity      = document.getElementById('label-city');
const errCity        = document.getElementById('err-city');
const comment        = document.getElementById('comment');
const tg             = document.getElementById('tg');
const notice         = document.getElementById('notice');
const noticeText     = document.getElementById('notice-text');
const bIssue         = document.getElementById('block-issue');
const bCity          = document.getElementById('block-city');
const bComment       = document.getElementById('block-comment');
const inputCat       = document.getElementById('input-category');
const inputSub       = document.getElementById('input-sub-option');

function createEmptyTabState() {
  const now = new Date();
  return {
    choice: null,
    timeChoice: null,
    exactDate: '',
    exactTime: '',
    pickerDate: '',
    pickerTime: '',
    selectedDate: now,
    selectedTimeStr: getDefaultTimeStr(now),
    location: '',
    comment: '',
    tg: '',
  };
}

const tabState = Object.fromEntries(Object.keys(SETS).map(id => [id, createEmptyTabState()]));
const choice = Object.fromEntries(Object.keys(SETS).map(id => [id, null]));
let timeChoice = null;

const UK_MONTHS = ['січ.', 'лют.', 'берез.', 'квіт.', 'трав.', 'черв.', 'лип.', 'серп.', 'верес.', 'жовт.', 'листоп.', 'груд.'];

function getDefaultDateStr(dateObj = new Date()) {
  const y = dateObj.getFullYear();
  const m = String(dateObj.getMonth() + 1).padStart(2, '0');
  const d = String(dateObj.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function getDefaultTimeStr(dateObj = new Date()) {
  return String(dateObj.getHours()).padStart(2, '0') + ':' + String(dateObj.getMinutes()).padStart(2, '0');
}

let selectedDate = new Date();
let selectedTimeStr = getDefaultTimeStr();
let tab = Object.keys(SETS)[0];

function formatUkrainianDate(dateObj) {
  const d = dateObj.getDate();
  const m = UK_MONTHS[dateObj.getMonth()];
  return `${d} ${m}`;
}

function formatUkrainianTime(timeStr, dateObj = new Date()) {
  if (timeStr && /^\d{1,2}:\d{2}$/.test(timeStr)) {
    const parts = timeStr.split(':');
    return `${parts[0].padStart(2, '0')}:${parts[1]}`;
  }
  return getDefaultTimeStr(dateObj);
}

function formatUkrainianDateTime(dateObj, timeStr) {
  return `${formatUkrainianDate(dateObj)} ${formatUkrainianTime(timeStr, dateObj)}`;
}

const isOther = () => SETS[tab].length === 0;

function render(){
  opts.innerHTML = SETS[tab].map((t, i) => `
    <label class="opt">
      <input type="radio" name="issue" value="${i}" ${choice[tab] === String(i) ? 'checked' : ''}>
      <span>${t}</span>
    </label>`).join('');

  renderTime();
}

function renderTime(){
  if (!optsTime) return;
  optsTime.innerHTML = TIME_OPTIONS.map(t => `
    <label class="opt">
      <input type="radio" name="time_opt" value="${t}" ${timeChoice === t ? 'checked' : ''}>
      <span>${t}</span>
    </label>`).join('');
  updateTimePickerVisibility();
}

function updateTimePickerVisibility(){
  if (!timePickerWrap) return;
  const isCustom = (timeChoice === 'Вибрати дату і час' || timeChoice === 'Вибрати час');
  timePickerWrap.classList.toggle('open', isCustom);
  if (!isCustom) {
    if (bTime) bTime.classList.remove('picker-invalid');
    if (exactDate) {
      exactDate.value = '';
      exactDate.classList.remove('invalid');
    }
    if (exactTime) {
      exactTime.value = '';
      exactTime.classList.remove('invalid');
    }
  }
}

function updateTabUI(){
  if (comment) {
    comment.placeholder = isOther()
      ? 'Опишіть, будь ласка, що саме сталося'
      : 'Якщо хочете додати щось ще';
  }

  if (tab === 'alerts') {
    if (labelCity) labelCity.textContent = 'Місто';
    if (city) {
      city.placeholder = 'Наприклад, Чернігів';
      city.setAttribute('aria-label', 'Місто');
    }
    if (errCity) errCity.textContent = 'Вкажіть, будь ласка, місто — без нього ми не знайдемо збій.';
  } else if (tab === 'map') {
    if (labelCity) labelCity.textContent = 'Район';
    if (city) {
      city.placeholder = 'Наприклад, Чернігівський район';
      city.setAttribute('aria-label', 'Район');
    }
    if (errCity) errCity.textContent = 'Вкажіть, будь ласка, район — без нього ми не знайдемо збій.';
  } else {
    if (labelCity) labelCity.textContent = 'Місто або район';
    if (city) {
      city.placeholder = 'Наприклад, Чернігів або Чернігівський район';
      city.setAttribute('aria-label', 'Місто або район');
    }
    if (errCity) errCity.textContent = 'Вкажіть, будь ласка, місто або район.';
  }
}

function syncInputs(){
  inputCat.value = TAB_CATEGORIES[tab];
  inputSub.value = choice[tab] !== null ? (SETS[tab][choice[tab]] || '') : '';
}

opts.addEventListener('change', e => {
  choice[tab] = e.target.value;
  syncInputs();
  bIssue.classList.remove('invalid');
});

function openDatePicker() {
  if (!pickerDate) return;
  if (!pickerDate.value) {
    pickerDate.value = getDefaultDateStr(selectedDate);
  }
  if (exactDate) {
    const rect = exactDate.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 320) {
      window.scrollBy({ top: 320 - spaceBelow, behavior: 'smooth' });
    }
  }
  try {
    if (typeof pickerDate.showPicker === 'function') {
      pickerDate.showPicker();
      return;
    }
  } catch (e) {}
  pickerDate.focus();
}

function openTimePicker() {
  if (!pickerTime) return;
  if (!pickerTime.value) {
    pickerTime.value = selectedTimeStr;
  }
  if (exactTime) {
    const rect = exactTime.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 280) {
      window.scrollBy({ top: 280 - spaceBelow, behavior: 'smooth' });
    }
  }
  try {
    if (typeof pickerTime.showPicker === 'function') {
      pickerTime.showPicker();
      return;
    }
  } catch (e) {}
  pickerTime.focus();
}

if (optsTime) {
  optsTime.addEventListener('click', e => {
    const optLabel = e.target.closest('.opt');
    if (!optLabel) return;
    const radio = optLabel.querySelector('input[type="radio"]');
    if (!radio) return;
    const val = radio.value;
    if (val === 'Вибрати дату і час' || val === 'Вибрати час') {
      timeChoice = val;
      radio.checked = true;
      if (bTime) {
        bTime.classList.remove('picker-invalid', 'invalid');
      }
      if (exactDate) exactDate.classList.remove('invalid');
      if (exactTime) exactTime.classList.remove('invalid');
      selectedDate = new Date();
      selectedTimeStr = getDefaultTimeStr(selectedDate);
      if (exactDate) {
        exactDate.value = '';
        exactDate.placeholder = formatUkrainianDate(selectedDate);
      }
      if (exactTime) {
        exactTime.value = '';
        exactTime.placeholder = formatUkrainianTime(selectedTimeStr, selectedDate);
      }
      if (pickerDate) pickerDate.value = getDefaultDateStr(selectedDate);
      if (pickerTime) pickerTime.value = selectedTimeStr;
      updateTimePickerVisibility();
    }
  });

  optsTime.addEventListener('change', e => {
    timeChoice = e.target.value;
    const isCustom = (timeChoice === 'Вибрати дату і час' || timeChoice === 'Вибрати час');
    if (isCustom) {
      if (bTime) {
        bTime.classList.remove('picker-invalid');
      }
      if (exactDate) exactDate.classList.remove('invalid');
      if (exactTime) exactTime.classList.remove('invalid');
      selectedDate = new Date();
      selectedTimeStr = getDefaultTimeStr(selectedDate);
      if (exactDate) {
        exactDate.value = '';
        exactDate.placeholder = formatUkrainianDate(selectedDate);
      }
      if (exactTime) {
        exactTime.value = '';
        exactTime.placeholder = formatUkrainianTime(selectedTimeStr, selectedDate);
      }
      if (pickerDate) pickerDate.value = getDefaultDateStr(selectedDate);
      if (pickerTime) pickerTime.value = selectedTimeStr;
    } else {
      if (bTime) bTime.classList.remove('picker-invalid');
      if (exactDate) exactDate.classList.remove('invalid');
      if (exactTime) exactTime.classList.remove('invalid');
    }
    if (bTime) bTime.classList.remove('invalid');
    renderTime();
  });
}

if (exactDate) {
  exactDate.addEventListener('click', e => {
    e.preventDefault();
    timeChoice = 'Вибрати дату і час';
    exactDate.focus();
    openDatePicker();
  });
}

if (exactTime) {
  exactTime.addEventListener('click', e => {
    e.preventDefault();
    timeChoice = 'Вибрати дату і час';
    exactTime.focus();
    openTimePicker();
  });
}

if (pickerDate) {
  pickerDate.addEventListener('change', () => {
    if (pickerDate.value) {
      selectedDate = new Date(pickerDate.value + 'T00:00:00');
    }
    if (exactDate) {
      exactDate.value = formatUkrainianDate(selectedDate);
      exactDate.classList.remove('invalid');
    }
    const hasTime = exactTime && !!exactTime.value.trim();
    if (hasTime) {
      if (bTime) bTime.classList.remove('invalid', 'picker-invalid');
    } else if (bTime && bTime.classList.contains('invalid')) {
      if (errTime) errTime.textContent = 'Вкажіть, будь ласка, час.';
    }
  });
}

if (pickerTime) {
  pickerTime.addEventListener('change', () => {
    if (pickerTime.value) {
      selectedTimeStr = pickerTime.value;
    }
    if (exactTime) {
      exactTime.value = formatUkrainianTime(selectedTimeStr, selectedDate);
      exactTime.classList.remove('invalid');
    }
    const hasDate = exactDate && !!exactDate.value.trim();
    if (hasDate) {
      if (bTime) bTime.classList.remove('invalid', 'picker-invalid');
    } else if (bTime && bTime.classList.contains('invalid')) {
      if (errTime) errTime.textContent = 'Вкажіть, будь ласка, дату.';
    }
  });
}

tabs.forEach((b, i) => {
  b.addEventListener('click', () => select(i));
  b.addEventListener('keydown', e => {
    const step = {ArrowRight:1, ArrowDown:1, ArrowLeft:-1, ArrowUp:-1}[e.key];
    if(!step) return;
    e.preventDefault();
    const next = (i + step + tabs.length) % tabs.length;
    select(next); tabs[next].focus();
  });
});

function saveTabState(t) {
  if (!t || !tabState[t]) return;
  const s = tabState[t];
  s.choice = choice[t];
  s.timeChoice = timeChoice;
  s.exactDate = exactDate ? exactDate.value : '';
  s.exactTime = exactTime ? exactTime.value : '';
  s.pickerDate = pickerDate ? pickerDate.value : '';
  s.pickerTime = pickerTime ? pickerTime.value : '';
  s.selectedDate = selectedDate;
  s.selectedTimeStr = selectedTimeStr;
  s.location = city ? city.value : '';
  s.comment = comment ? comment.value : '';
  s.tg = tg ? tg.value : '';
}

function restoreTabState(t) {
  const s = tabState[t];
  if (!s) return;
  choice[t] = s.choice;
  timeChoice = s.timeChoice;
  selectedDate = s.selectedDate || new Date();
  selectedTimeStr = s.selectedTimeStr || getDefaultTimeStr(selectedDate);

  if (exactDate) {
    exactDate.value = s.exactDate || '';
    exactDate.placeholder = formatUkrainianDate(selectedDate);
    exactDate.classList.remove('invalid');
  }
  if (exactTime) {
    exactTime.value = s.exactTime || '';
    exactTime.placeholder = formatUkrainianTime(selectedTimeStr, selectedDate);
    exactTime.classList.remove('invalid');
  }
  if (pickerDate) {
    pickerDate.value = s.pickerDate || (s.timeChoice === 'Вибрати дату і час' || s.timeChoice === 'Вибрати час' ? getDefaultDateStr(selectedDate) : '');
  }
  if (pickerTime) {
    pickerTime.value = s.pickerTime || (s.timeChoice === 'Вибрати дату і час' || s.timeChoice === 'Вибрати час' ? selectedTimeStr : '');
  }
  if (city) {
    city.value = s.location || '';
  }
  if (comment) {
    comment.value = s.comment || '';
  }
  if (tg) {
    tg.value = s.tg || '';
  }
}

function select(i){
  saveTabState(tab);

  tabs.forEach((x, j) => {
    x.setAttribute('aria-checked', String(j === i));
    x.tabIndex = j === i ? 0 : -1;
  });
  if (segSlider) {
    segSlider.style.transform = `translateX(${i * 100}%)`;
  }
  tab = tabs[i].dataset.tab;
  restoreTabState(tab);
  document.body.classList.toggle('tab-other', isOther());
  comboClose();

  bIssue.classList.remove('invalid');
  if (bTime) bTime.classList.remove('invalid', 'picker-invalid');
  if (exactDate) exactDate.classList.remove('invalid');
  if (exactTime) exactTime.classList.remove('invalid');
  if (errTime) errTime.textContent = 'Оберіть, будь ласка, коли це сталося.';
  bCity.classList.remove('invalid');
  bComment.classList.remove('invalid');
  if (errComment) errComment.textContent = 'Опишіть, будь ласка, що сталося — без цього ми не знатимемо, що шукати.';

  updateTabUI();
  syncInputs();
  render();
  checkCommentOverflow();
}

const THUMB_MIN = 24;

function attachScrollbar(view){
  const host = view.parentElement;
  if(!host || !host.classList.contains('scroller')) return null;

  const bar = document.createElement('div');
  bar.className = 'scroller-bar';
  bar.setAttribute('aria-hidden', 'true');
  const thumb = document.createElement('div');
  thumb.className = 'scroller-thumb';
  bar.appendChild(thumb);
  host.appendChild(bar);
  host.classList.add('is-live');

  const range = () => view.scrollHeight - view.clientHeight;

  function update(){
    const max = range();
    host.classList.toggle('is-scrollable', max > 1);
    if(max <= 1) return;
    const track  = bar.clientHeight;
    const height = Math.max(THUMB_MIN, Math.round(track * view.clientHeight / view.scrollHeight));
    thumb.style.height = height + 'px';
    thumb.style.transform = `translateY(${Math.round((track - height) * view.scrollTop / max)}px)`;
  }

  let fromY = 0, fromTop = 0;

  thumb.addEventListener('pointerdown', e => {
    e.preventDefault();
    thumb.setPointerCapture(e.pointerId);
    host.classList.add('is-dragging');
    fromY = e.clientY;
    fromTop = view.scrollTop;
  });

  thumb.addEventListener('pointermove', e => {
    if(!host.classList.contains('is-dragging')) return;
    const free = bar.clientHeight - thumb.offsetHeight;
    if(free > 0) view.scrollTop = fromTop + (e.clientY - fromY) * range() / free;
  });

  const drop = () => host.classList.remove('is-dragging');
  thumb.addEventListener('pointerup', drop);
  thumb.addEventListener('pointercancel', drop);

  bar.addEventListener('pointerdown', e => {
    if(e.target === thumb) return;
    const free = bar.clientHeight - thumb.offsetHeight;
    if(free <= 0) return;
    const at = e.clientY - bar.getBoundingClientRect().top - thumb.offsetHeight / 2;
    view.scrollTop = Math.min(Math.max(at, 0), free) * range() / free;
  });

  view.addEventListener('scroll', update, {passive:true});
  view.addEventListener('input', update);
  window.addEventListener('resize', update);
  if(window.ResizeObserver) new ResizeObserver(update).observe(view);
  if(document.fonts) document.fonts.ready.then(update);
  update();

  return {update};
}

const combo      = document.getElementById('combo-city');
const cityList   = document.getElementById('city-list');
const cityScroll = attachScrollbar(cityList);
let comboItems  = [];
let comboIndex  = -1;

const norm = s => s.toLowerCase().replace(/ʼ|'|’/g, "'").trim();

function comboMatch(q){
  const items = (tab === 'alerts') ? CITIES
              : (tab === 'map') ? DISTRICTS
              : [...CITIES, ...DISTRICTS];
  if(!q) return items;
  const n = norm(q);
  return items.filter(item => {
    const full = norm(item);
    if (full.startsWith(n)) return true;
    const words = full.split(/[\s\.\-]+/).filter(Boolean);
    return words.some(w => w.startsWith(n));
  });
}

function comboRender(q){
  comboItems = comboMatch(q);
  comboIndex = -1;
  if(!comboItems.length){
    if(tab === 'alerts' && q){
      cityList.innerHTML = '<li class="combo-empty" role="presentation">Не знайшли такого міста — можна ввести свою назву</li>';
      comboOpen();
      if(cityScroll) cityScroll.update();
    } else {
      comboClose();
    }
    return;
  }

  const n = norm(q);
  cityList.innerHTML = comboItems.map((c, i) => {
    let label = c;
    if(n){
      const full = norm(c);
      let at = -1;
      if (full.startsWith(n)) {
        at = 0;
      } else {
        const re = new RegExp(`(^|[\\s\\.\\-])${n.replace(/[.*+?^${}()|[\\]\\]/g, '\\$&')}`, 'i');
        const m = c.match(re);
        if (m) {
          at = m.index + m[1].length;
        }
      }
      if(at > -1){
        label = c.slice(0, at) + '<b>' + c.slice(at, at + n.length) + '</b>' + c.slice(at + n.length);
      }
    }
    return `<li class="combo-option" role="option" id="city-opt-${i}" aria-selected="false">${label}</li>`;
  }).join('');
  comboOpen();
  if(cityScroll) cityScroll.update();
}

function comboOpen(){
  combo.classList.add('open');
  city.setAttribute('aria-expanded', 'true');
}

function comboClose(){
  combo.classList.remove('open');
  city.setAttribute('aria-expanded', 'false');
  city.removeAttribute('aria-activedescendant');
  comboIndex = -1;
}

function comboHighlight(i){
  const nodes = [...cityList.children];
  nodes.forEach((n, j) => n.setAttribute('aria-selected', String(j === i)));
  comboIndex = i;
  if(i > -1){
    city.setAttribute('aria-activedescendant', 'city-opt-' + i);
    nodes[i].scrollIntoView({block:'nearest'});
  } else {
    city.removeAttribute('aria-activedescendant');
  }
}

function comboPick(i){
  if(i < 0 || i >= comboItems.length) return;
  city.value = comboItems[i];
  if (tab && tabState[tab]) tabState[tab].location = city.value;
  bCity.classList.remove('invalid');
  comboClose();
}

city.addEventListener('input', () => {
  if (tab && tabState[tab]) tabState[tab].location = city.value;
  bCity.classList.remove('invalid');
  comboRender(city.value);
});

city.addEventListener('focus', () => comboRender(city.value));

city.addEventListener('keydown', e => {
  if(e.key === 'ArrowDown' || e.key === 'ArrowUp'){
    e.preventDefault();
    if(!combo.classList.contains('open')){ comboRender(city.value); return; }
    const step = e.key === 'ArrowDown' ? 1 : -1;
    const len  = comboItems.length;
    comboHighlight((comboIndex + step + len + (comboIndex === -1 && step === -1 ? 1 : 0)) % len);
  } else if(e.key === 'Enter'){
    if(combo.classList.contains('open') && comboIndex > -1){
      e.preventDefault();
      comboPick(comboIndex);
    }
  } else if(e.key === 'Escape' || e.key === 'Tab'){
    comboClose();
  }
});

cityList.addEventListener('mousedown', e => {
  const li = e.target.closest('.combo-option');
  if(!li) return;
  e.preventDefault();
  comboPick([...cityList.children].indexOf(li));
  city.focus();
});

cityList.addEventListener('mousemove', e => {
  const li = e.target.closest('.combo-option');
  if(li) comboHighlight([...cityList.children].indexOf(li));
});

document.addEventListener('pointerdown', e => {
  if(!combo.contains(e.target)) comboClose();
});

const COMMENT_MAX = 1000;
const errComment = bComment.querySelector('.err');

function checkCommentOverflow() {
  let hasOverflow = false;
  if (comment.value.length > COMMENT_MAX) {
    comment.value = comment.value.slice(0, COMMENT_MAX);
    hasOverflow = true;
  }
  while (comment.scrollHeight > comment.clientHeight && comment.value.length > 0) {
    comment.value = comment.value.slice(0, -1);
    hasOverflow = true;
  }
  if (hasOverflow) {
    bComment.classList.add('invalid');
    if (errComment) {
      errComment.textContent = 'Скоротіть, будь ласка, коментар — він занадто довгий.';
    }
  } else {
    if (bComment.classList.contains('invalid')) {
      const isOtherTab = isOther();
      if (!isOtherTab || comment.value.trim().length > 0) {
        bComment.classList.remove('invalid');
        if (errComment) {
          errComment.textContent = 'Опишіть, будь ласка, що сталося — без цього ми не знатимемо, що шукати.';
        }
      }
    }
  }
}

comment.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'Tab', 'Escape'].includes(e.key)) {
    return;
  }
  const hasSelection = comment.selectionStart !== comment.selectionEnd;
  if (!hasSelection && (comment.scrollHeight > comment.clientHeight || comment.value.length >= COMMENT_MAX)) {
    e.preventDefault();
    bComment.classList.add('invalid');
    if (errComment) {
      errComment.textContent = 'Скоротіть, будь ласка, коментар — він занадто довгий.';
    }
  }
});

comment.addEventListener('paste', () => {
  setTimeout(checkCommentOverflow, 0);
});

comment.addEventListener('input', () => {
  if (tab && tabState[tab]) tabState[tab].comment = comment.value;
  checkCommentOverflow();
});

if (tg) {
  tg.addEventListener('input', () => {
    if (tab && tabState[tab]) tabState[tab].tg = tg.value;
  });
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  if (comment.value.length > COMMENT_MAX) {
    comment.value = comment.value.slice(0, COMMENT_MAX);
  }

  const isOtherTab = isOther();
  const noIssue = !isOtherTab && (choice[tab] === null || choice[tab] === undefined);
  
  let noTime = false;
  let missingDate = false;
  let missingTime = false;
  let isCustomTimeSelected = false;

  if (!isOtherTab) {
    if (!timeChoice) {
      noTime = true;
    } else if (timeChoice === 'Вибрати дату і час' || timeChoice === 'Вибрати час') {
      isCustomTimeSelected = true;
      const hasDate = exactDate ? !!exactDate.value.trim() : false;
      const hasTime = exactTime ? !!exactTime.value.trim() : false;
      if (!hasDate) missingDate = true;
      if (!hasTime) missingTime = true;
      if (missingDate || missingTime) {
        noTime = true;
      }
    }
  }

  if (errTime) {
    if (isCustomTimeSelected) {
      if (missingDate && missingTime) {
        errTime.textContent = 'Вкажіть, будь ласка, дату і час.';
      } else if (missingDate) {
        errTime.textContent = 'Вкажіть, будь ласка, дату.';
      } else if (missingTime) {
        errTime.textContent = 'Вкажіть, будь ласка, час.';
      }
    } else {
      errTime.textContent = 'Оберіть, будь ласка, коли це сталося.';
    }
  }

  const noComment = isOtherTab && !comment.value.trim();
  const noLocation = !isOtherTab && !city.value.trim();

  bIssue.classList.toggle('invalid', noIssue);
  if (bTime) {
    bTime.classList.toggle('invalid', noTime);
    bTime.classList.toggle('picker-invalid', isCustomTimeSelected && noTime);
  }
  if (exactDate) {
    exactDate.classList.toggle('invalid', isCustomTimeSelected && missingDate);
  }
  if (exactTime) {
    exactTime.classList.toggle('invalid', isCustomTimeSelected && missingTime);
  }
  bComment.classList.toggle('invalid', noComment);
  if (errComment) {
    errComment.textContent = 'Опишіть, будь ласка, що сталося — без цього ми не знатимемо, що шукати.';
  }
  bCity.classList.toggle('invalid', noLocation);

  if (noIssue || noTime || noComment || noLocation) {
    let first = null;
    if (noIssue) {
      first = opts.querySelector('input');
    } else if (noTime) {
      if (isCustomTimeSelected) {
        if (missingDate) {
          first = exactDate;
        } else if (missingTime) {
          first = exactTime;
        } else {
          first = exactDate || exactTime;
        }
      } else {
        first = optsTime ? optsTime.querySelector('input') : null;
      }
    } else if (noComment) {
      first = comment;
    } else {
      first = city;
    }
    if (first) first.focus();
    return;
  }

  syncInputs();

  const submitBtn = form.querySelector('.submit');
  submitBtn.disabled = true;

  const formData = new FormData();
  formData.append('category', TAB_CATEGORIES[tab]);
  formData.append('sub_option', choice[tab] !== null ? (SETS[tab][choice[tab]] || '') : '');
  
  const isCustomTime = (timeChoice === 'Вибрати дату і час' || timeChoice === 'Вибрати час');
  const chosenTime = isOtherTab ? '' : (isCustomTime
    ? `${exactDate ? exactDate.value.trim() : ''} ${exactTime ? exactTime.value.trim() : ''}`.trim()
    : (timeChoice || ''));
  if (chosenTime) {
    formData.append('time', chosenTime);
    if (isCustomTime) {
      if (pickerDate) formData.append('exact_date', pickerDate.value || getDefaultDateStr(selectedDate));
      if (pickerTime) formData.append('exact_time', pickerTime.value || selectedTimeStr);
    }
  }

  const locVal = isOtherTab ? '' : city.value.trim();
  if (locVal) {
    if (tab === 'map') {
      formData.append('district', locVal);
      formData.append('city', locVal);
    } else {
      formData.append('city', locVal);
    }
  }

  formData.append('message', comment.value.trim());
  formData.append('contact', tg.value.trim());

  try {
    const res = await fetch('/issue', {
      method: 'POST',
      body: formData,
    });

    if (res.ok) {
      resetForm();
      showNotice('ok', MSG.ok);
    } else if (res.status === 429) {
      showNotice('error', MSG.tooMany);
    } else {
      showNotice('error', MSG.failed);
    }
  } catch (err) {
    showNotice('error', MSG.offline);
  } finally {
    submitBtn.disabled = false;
  }
});

const NOTICE_MS = 20000;
let noticeTimer;

const MSG = {
  ok:      'Дякуємо, повідомлення отримали. Розберемось.',
  failed:  'Щось пішло не так — повідомлення не надіслалось. Спробуйте, будь ласка, пізніше.',
  tooMany: 'Забагато повідомлень поспіль. Спробуйте, будь ласка, за годину — попередні вже в роботі.',
  offline: 'Немає зʼєднання. Перевірте інтернет і спробуйте ще раз.'
};

function resetForm(){
  form.reset();
  Object.keys(tabState).forEach(k => {
    tabState[k] = createEmptyTabState();
  });
  Object.keys(choice).forEach(k => choice[k] = null);
  timeChoice = null;
  selectedDate = new Date();
  selectedTimeStr = getDefaultTimeStr(selectedDate);
  if (city) city.value = '';
  if (comment) comment.value = '';
  if (tg) tg.value = '';
  if (exactDate) {
    exactDate.value = '';
    exactDate.placeholder = formatUkrainianDate(selectedDate);
    exactDate.classList.remove('invalid');
  }
  if (exactTime) {
    exactTime.value = '';
    exactTime.placeholder = formatUkrainianTime(selectedTimeStr, selectedDate);
    exactTime.classList.remove('invalid');
  }
  if (pickerDate) pickerDate.value = '';
  if (pickerTime) pickerTime.value = '';
  renderTime();
  bIssue.classList.remove('invalid');
  if (bTime) bTime.classList.remove('invalid', 'picker-invalid');
  if (errTime) errTime.textContent = 'Оберіть, будь ласка, коли це сталося.';
  bCity.classList.remove('invalid');
  bComment.classList.remove('invalid');
  if (errComment) errComment.textContent = 'Опишіть, будь ласка, що сталося — без цього ми не знатимемо, що шукати.';
  comboClose();
  select(0);
}

function showNotice(kind, text){
  clearTimeout(noticeTimer);
  noticeText.textContent = text;
  notice.classList.toggle('notice--error', kind === 'error');
  notice.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');
  notice.classList.add('show');

  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({top:0, behavior: still ? 'auto' : 'smooth'});

  noticeTimer = setTimeout(() => {
    document.body.classList.remove('sent');
    notice.classList.remove('show');
  }, NOTICE_MS);
}

if (exactDate) exactDate.placeholder = formatUkrainianDate(selectedDate);
if (exactTime) exactTime.placeholder = formatUkrainianTime(selectedTimeStr, selectedDate);
select(0);

if (document.body.classList.contains('sent')) showNotice('ok', MSG.ok);

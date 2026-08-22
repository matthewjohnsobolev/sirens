/**
 * Сторінка «Повідомити про помилку»: розділи, автодоповнення міста,
 * перевірка полів і відправка.
 *
 * Перелік розділів, варіантів і міст сюди не вписаний - він приїздить із
 * сервера в <script id="report-config">, бо тим самим переліком сервер
 * перевіряє те, що прийшло (web/report_form.py). Другий примірник тут
 * розійшовся б із ним першим.
 */

const CONFIG = JSON.parse(document.getElementById('report-config').textContent);

/* Варіанти розділу. У «Іншому» перелік порожній навмисно: там людина описує
   проблему словами, тож замість варіантів першим іде коментар. */
const SETS = CONFIG.sets;

/* Вкладка -> назва, під якою звернення ляже в базу й прийде в Telegram. */
const TAB_CATEGORIES = CONFIG.categories;

const form      = document.getElementById('report-form');
const opts      = document.getElementById('opts');
const tabs      = [...document.querySelectorAll('.seg button')];
const segSlider = document.getElementById('seg-slider');
const city      = document.getElementById('city');
const comment   = document.getElementById('comment');
const tg        = document.getElementById('tg');
const notice    = document.getElementById('notice');
const noticeText= document.getElementById('notice-text');
const bIssue    = document.getElementById('block-issue');
const bCity     = document.getElementById('block-city');
const bComment  = document.getElementById('block-comment');
const inputCat  = document.getElementById('input-category');
const inputSub  = document.getElementById('input-sub-option');

/* Обраний варіант кожного розділу окремо: перемкнувся туди-сюди - вибір
   лишився. Ключі беруться з довідника, тож новий розділ на сервері не
   потребує правки тут. */
const choice = Object.fromEntries(Object.keys(SETS).map(id => [id, null]));
let tab = Object.keys(SETS)[0];
/* Розділ без переліку - той, де суть звернення несе коментар, а не вибір.
   Питаємо про це самі дані, а не назву вкладки: розділ може називатись
   як завгодно, порожній перелік означає те саме. */
const isOther = () => SETS[tab].length === 0;

function render(){
  opts.innerHTML = SETS[tab].map((t,i) => `
    <label class="opt">
      <input type="radio" name="issue" value="${i}" ${choice[tab] === String(i) ? 'checked' : ''}>
      <span>${t}</span>
    </label>`).join('');
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

function select(i){
  tabs.forEach((x, j) => {
    x.setAttribute('aria-checked', String(j === i));
    x.tabIndex = j === i ? 0 : -1;
  });
  if (segSlider) {
    segSlider.style.transform = `translateX(${i * 100}%)`;
  }
  tab = tabs[i].dataset.tab;
  document.body.classList.toggle('tab-other', isOther());
  /* помилки попереднього розділу не переносяться на новий */
  bIssue.classList.remove('invalid');
  bComment.classList.remove('invalid');
  syncInputs();
  render();
}

comment.addEventListener('input', () => bComment.classList.remove('invalid'));

/* --- Автодоповнення міста -------------------------------------------------
   Підказує рівно ті міста, куди йде сповіщення: скаржаться на те, чого
   чекали, а чекати його можна тільки там, де є канал. Поле при цьому
   лишається вільним - список підказує, але не обмежує. */
const CITIES = CONFIG.cities;

const combo     = document.getElementById('combo-city');
const cityList  = document.getElementById('city-list');
let comboItems  = [];
let comboIndex  = -1;

const norm = s => s.toLowerCase().replace(/ʼ|'|’/g, "'").trim();

function comboMatch(q){
  if(!q) return CITIES;
  const n = norm(q);
  /* спочатку ті, що починаються на введене, потім ті, де воно всередині:
     «Рівне» має стояти вище за «Кривий Ріг», коли набрано «рів» */
  const starts = CITIES.filter(c => norm(c).startsWith(n));
  const inside = CITIES.filter(c => !norm(c).startsWith(n) && norm(c).includes(n));
  return [...starts, ...inside];
}

function comboRender(q){
  comboItems = comboMatch(q);
  comboIndex = -1;
  if(!comboItems.length){ comboClose(); return; }

  const n = norm(q);
  cityList.innerHTML = comboItems.map((c, i) => {
    let label = c;
    if(n){
      const at = norm(c).indexOf(n);
      if(at > -1){
        label = c.slice(0, at) + '<b>' + c.slice(at, at + n.length) + '</b>' + c.slice(at + n.length);
      }
    }
    return `<li class="combo-option" role="option" id="city-opt-${i}" aria-selected="false">${label}</li>`;
  }).join('');
  comboOpen();
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
  bCity.classList.remove('invalid');
  comboClose();
}

city.addEventListener('input', () => {
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
    /* Enter підтверджує підказку, а не надсилає форму */
    if(combo.classList.contains('open') && comboIndex > -1){
      e.preventDefault();
      comboPick(comboIndex);
    }
  } else if(e.key === 'Escape' || e.key === 'Tab'){
    comboClose();
  }
});

/* mousedown, а не click: інакше поле встигає втратити фокус і список
   закривається раніше, ніж спрацює вибір */
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

/* pointerdown, а не click: на iOS click не завжди спливає з неінтерактивних
   елементів, і список лишався б відкритим після тапу повз нього. */
document.addEventListener('pointerdown', e => {
  if(!combo.contains(e.target)) comboClose();
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const noIssue   = !isOther() && (choice[tab] === null || choice[tab] === undefined);
  const noComment = isOther() && !comment.value.trim();
  const noCity    = !city.value.trim();

  bIssue.classList.toggle('invalid', noIssue);
  bComment.classList.toggle('invalid', noComment);
  bCity.classList.toggle('invalid', noCity);

  if(noIssue || noComment || noCity){
    /* фокус - на першому незаповненому в порядку показу */
    const first = noIssue ? opts.querySelector('input')
                : noComment ? comment
                : city;
    first.focus();
    return;
  }

  syncInputs();

  const submitBtn = form.querySelector('.submit');
  submitBtn.disabled = true;

  const formData = new FormData();
  formData.append('category', TAB_CATEGORIES[tab]);
  formData.append('sub_option', choice[tab] !== null ? (SETS[tab][choice[tab]] || '') : '');
  formData.append('city', city.value.trim());
  formData.append('message', comment.value.trim());
  formData.append('contact', tg.value.trim());

  try {
    const res = await fetch('/report-error', {
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

/* --- Повідомлення ---------------------------------------------------------
   Одна таблетка на два результати: зелена, коли звернення пішло, оранжева,
   коли ні. Живе 10 секунд над перемикачем розділів. Сторінку піднімає до
   початку - кнопка «Надіслати» стоїть унизу, і без цього повідомлення
   з'явилось би поза екраном. 20 секунд: на телефоні між появою таблетки
   й тим, як людина підніме погляд від клавіатури, минає більше часу.
   Після успіху форма чиста; після збою - навпаки, недоторкана: набране
   людиною має дочекатись повторної спроби. */
const NOTICE_MS = 20000;
let noticeTimer;

const MSG = {
  ok:      'Повідомлення надіслано — перевіримо найближчим часом.',
  failed:  'Щось пішло не так — повідомлення не надіслалось. Спробуйте, будь ласка, пізніше.',
  tooMany: 'Забагато повідомлень поспіль. Спробуйте, будь ласка, за годину — попередні вже в роботі.',
  offline: 'Немає зʼєднання. Перевірте інтернет і спробуйте ще раз.'
};

function resetForm(){
  form.reset();
  Object.keys(choice).forEach(k => choice[k] = null);
  bIssue.classList.remove('invalid');
  bCity.classList.remove('invalid');
  bComment.classList.remove('invalid');
  comboClose();
  select(0);
}

function showNotice(kind, text){
  clearTimeout(noticeTimer);
  noticeText.textContent = text;
  notice.classList.toggle('notice--error', kind === 'error');
  /* збій читалка озвучує негайно, успіх - у свою чергу */
  notice.setAttribute('aria-live', kind === 'error' ? 'assertive' : 'polite');

  /* Таблетка завжди в розмітці й лише розгортається, тож ні display, ні
     примусового перерахунку не потрібно - один клас робить усе. */
  notice.classList.add('show');

  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({top:0, behavior: still ? 'auto' : 'smooth'});

  noticeTimer = setTimeout(() => {
    /* body.sent тримає таблетку відкритою на сторінці, яку сервер віддав уже
       з успіхом; знімати його треба разом із .show, інакше вона лишиться
       відкритою й закриється стрибком. */
    document.body.classList.remove('sent');
    notice.classList.remove('show');
  }, NOTICE_MS);
}

select(0);

/* Якщо сторінку віддав сервер уже з успіхом (форма пішла звичайним POST,
   без fetch), таблетка поводиться так само. */
if (document.body.classList.contains('sent')) showNotice('ok', MSG.ok);

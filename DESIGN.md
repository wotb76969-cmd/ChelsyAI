---
name: Chelsy AI
description: Личный ИИ-ассистент на своём железе; спокойный чат полярной ночи, где светится только работа Челси.
colors:
  background: "#0B0C20"
  panel: "#11132B"
  panel-2: "#161937"
  raised: "#1C2046"
  selected: "#2A2160"
  stroke: "#262A52"
  violet: "#6D4AFF"
  violet-hover: "#7D5DFF"
  lavender: "#A78BFA"
  teal: "#21D9DA"
  text: "#ECEBFA"
  muted: "#A3A6C8"
  user-bubble: "#231D4F"
  code-bg: "#0E1029"
  danger: "#FF8A65"
typography:
  display:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.3
  headline:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  body-small:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.4
  caption:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    letterSpacing: "0.6px"
  mono:
    fontFamily: "ChelsyMono, JetBrains Mono, Cascadia Code, Consolas, monospace"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  date:
    fontFamily: "Segoe UI, Roboto, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    fontFeature: "tnum"
rounded:
  tail: "6px"
  row: "10px"
  md: "12px"
  field: "14px"
  xl: "20px"
  logo: "22px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.violet}"
    textColor: "#FFFFFF"
    rounded: "{rounded.field}"
    height: "48px"
    padding: "0 20px"
  button-primary-hover:
    backgroundColor: "{colors.violet-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.muted}"
  button-stop:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.danger}"
    rounded: "{rounded.md}"
  button-flat:
    backgroundColor: "transparent"
    textColor: "{colors.lavender}"
    padding: "4px 8px"
  composer:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.xl}"
    typography: "{typography.body}"
  user-bubble:
    backgroundColor: "{colors.user-bubble}"
    textColor: "{colors.text}"
    rounded: "{rounded.xl}"
    padding: "11px 16px"
  code-block:
    backgroundColor: "{colors.code-bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    typography: "{typography.mono}"
    padding: "12px"
  input-field:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
  list-row:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    rounded: "{rounded.row}"
    padding: "8px 12px"
  list-row-hover:
    backgroundColor: "{colors.raised}"
  list-row-selected:
    backgroundColor: "{colors.selected}"
    textColor: "{colors.text}"
  chip-filter:
    backgroundColor: "{colors.panel-2}"
    textColor: "{colors.text}"
    rounded: "{rounded.pill}"
  chip-filter-selected:
    backgroundColor: "{colors.selected}"
  example-card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    rounded: "{rounded.field}"
    padding: "14px"
---

# Design System: Chelsy AI

Записано по выпущенному коду линейки 0.9.x (Android `Android_Client/lib/src/theme.dart`, Windows Client
`ChelsyAI_0.9_Windows/client_gui.py`, Desktop `ChelsyAI_0.9_Windows/app.py` → `CSS`, `THEME_VALUES`).
Бренд из `PRODUCT.md → Brand Commitments` обязателен и стоит выше этого файла. UX-правила и контраст —
в `design-system/chelsy-ai/MASTER.md` и `pages/android.md`, `pages/windows-client.md` (ui-ux-pro-max);
этот файл их не заменяет, а фиксирует визуальную систему «Северного сияния».

## Overview

**Creative North Star: "Северное сияние"**

Спокойная полярная ночь, в которой единственный свет — это Челси за работой. Фон тёмный и ровный,
глубина строится двумя-тремя тональными ступенями, а не тенями и не рамками. Бренд-градиент
(фиолетовый → лавандовый → бирюзовый) живёт в одном месте — тонкой «линии горизонта» над полем ввода:
в покое он тусклый и неподвижный, во время ответа течёт, при поиске бирюзово пробегает, при
синхронизации дышит лавандой, без хоста становится ровным коралловым.

Разговор — главный герой: широкая колонка чтения, ответы Челси без рамок и подложек с логотипом-аватаром
слева, реплики пользователя — тихий приподнятый пузырь справа. Управление — стандартные контролы
каждой платформы (Material 3 на Android, ttk на Windows, Gradio на Desktop), окрашенные токенами, без
собственных «неоновых» карточек. Плотность средняя, акценты точечные: фиолетовый — действие,
лавандовый — ссылки и второстепенные действия, бирюзовый — даты, «готова» и поиск.

Отвергнуто подтверждённо: светящиеся неоновые карточки и градиентные пятна повсюду (категорийный
шаблон), копирование облика ChatGPT/Claude.

**Key Characteristics:**
- Полярная ночь `background` и тональные подъёмы `panel` → `panel-2` → `raised`.
- Аврора — только линия горизонта (3 px у поля ввода, 2 px неподвижная на пустом чате и входе).
- Основное действие — сплошной фиолетовый, активная строка — тональный `selected`, не цветная кромка.
- Даты источников — бирюзовые табличные цифры.
- Код — данные: моноширинный шрифт, «снег» на самой глубокой ночи.
- Движение только пока Челси работает; под «уменьшить движение» всё неподвижно.

## Colors

Тёмная, холодная, почти монохромная ночь с тремя брендовыми огнями, каждый со своей работой.

### Primary
- **Брендовый фиолетовый** (#6D4AFF): заливка основного действия (отправить, «Новый чат», «Войти», «В
  базу»), аватар-инициал профиля, выделение текста (45 % альфа). Белый текст на нём 5,15:1. На фоне сам
  по себе 3,75:1 — только заливки, иконки и крупный текст, никогда не основной текст.
- **Фиолетовый наведения** (#7D5DFF): hover/active основной кнопки на Windows и Desktop.

### Secondary
- **Лавандовый** (#A78BFA): ссылки и названия источников, плоские кнопки, автор «Chelsy» на Windows,
  курсор ввода, фокус поля на Android, иконки примеров на пустом чате, избранное. 7,1:1 на фоне.

### Tertiary
- **Бирюза сияния** (#21D9DA): даты (источники, журнал, таблицы базы знаний), состояние «готова» и
  «ищет», прогресс исследования на Android, включённый интернет-поиск, кольцо фокуса на Desktop
  (2 px, отступ 2 px). 11:1 на фоне.

### Neutral
- **Полярная ночь** (#0B0C20): фон приложения на всех поверхностях, app bar.
- **Первый подъём** (#11132B): боковая панель/drawer, баннеры, карточки примеров, строки исследований.
- **Поле** (#161937): поля ввода, композер, чипы, развёрнутая задача исследования.
- **Приподнятый** (#1C2046): hover строк, кнопка «Стоп», отключённая основная кнопка, inline-код, snackbar.
- **Выбранное** (#2A2160): выбранная беседа/строка, выбранный чип, ползунок скролла на Desktop.
- **Пузырь пользователя** (#231D4F): реплики пользователя (13,1:1 с текстом).
- **Глубокая ночь кода** (#0E1029): блоки кода.
- **Штрих** (#262A52): тонкие разделители, линия над источниками, рамки полей и блоков кода.
- **Снег** (#ECEBFA): основной текст (16,4:1).
- **Иней** (#A3A6C8): вторичный текст, подсказки, подписи разделов, иконки действий (8,1:1).
- **Коралл** (#FF8A65): хост недоступен, ошибки, текст «Стоп» (8,3:1). Не красный — тёплый, спокойный.

### Named Rules
**The One Horizon Rule.** Бренд-градиент рисуется только линией горизонта: 3 px сверху композера
(состояние Chelsy Pulse) и 2 px неподвижная тусклая (≈35–45 %) линия на пустом чате, экране входа и
приветствии Desktop. Кнопки, строки, карточки и фоны градиента не получают.

**The Solid Action Rule.** Основное действие — сплошной фиолетовый; на экране одна-две такие кнопки.
Второстепенные действия — плоские лавандовые или иконки цвета инея.

**The Tonal Selection Rule.** Активное и выбранное показывается тональным подъёмом (`raised` при
наведении, `selected` при выборе), никогда цветной полосой по краю.

## Typography

**Display/Body Font:** системный шрифт платформы — Roboto/шрифт устройства на Android, Segoe UI
(Segoe UI Variable Text на Desktop, Segoe UI Semibold для заголовков) на Windows и Desktop.
**Mono Font:** JetBrains Mono, встроенный в Android как `ChelsyMono` (Apache-2.0, `Android_Client/fonts`);
на Windows/Desktop — Cascadia Code → Consolas.

**Character:** нейтральный системный гротеск, чтобы русский текст читался без усилий и уважал
системный масштаб; характер даёт не шрифт, а свет и ритм. Внешних веб-шрифтов и CDN нет.

### Hierarchy
- **Display** (600, 24 px): приветствие «Привет! Я Челси» на пустом чате; 28/700 — имя на экране входа.
- **Headline** (700, 22 px): h1 в ответах, заголовок страниц Desktop (22/600). h2 19/700, h3 17/600.
- **Title** (600, 17 px): app bar Android, заголовок беседы (16–17); titleLarge 20/600.
- **Body** (400, 16 px, 1,55): ответы и реплики на Android; Desktop 15,5 px / 1,62 (15 px на узком
  экране); Windows Segoe UI 11 pt. Колонка чтения ≤ 760 px.
- **Body small** (400, 14 px, 1,45): элементы списков, источники, примеры (14,5).
- **Label** (600, 12,5–13 px, иней): подписи разделов сайдбара, группы источников.
- **Caption** (600, 11 px, 0,6 px трекинг): версия «0.9.3 · beta», мелкие метки.
- **Mono** (400, 13,5 px, 1,5): код в ответах.
- **Date** (13 px, бирюза, `tnum`): даты источников и журнала.

### Named Rules
**The Tabular Date Rule.** Любая дата, процент или номер в списке — табличные цифры; даты бирюзовые и
не переносятся посреди значения.

**The Code Is Data Rule.** Код — моноширинный «снег» на `code-bg`, без построчных подложек; подсветка
синтаксиса на Desktop только снег / лавандовый (ключевые слова) / бирюза (строки, числа) / иней
курсивом (комментарии), всё ≥ 7:1.

## Layout

Чат-первый макет на всех поверхностях: сверху платформенная панель (заголовок, точка Chelsy Pulse,
избранное, меню), затем колонка разговора, внизу закреплённый композер с горизонтом, под ним выбор
модели и переключатель «Интернет». Боковая панель/drawer: «Новый чат» (основная кнопка), поиск,
Избранное, Недавние, разделы, профиль.

- **Android:** drawer на телефоне, постоянный сайдбар 300 dp при ширине ≥ 900; ответы до 90 % ширины
  (760 на широком), пузырь пользователя до 85 % от этого с отступом слева 40; композер с отступами
  12/4/12/8. Цели касания ≥ 48 dp, строки источников ≥ 44.
- **Windows Client:** сайдбар `panel`, контент с отступами 20/14/20/12; пузырь пользователя начинается
  с 38 % ширины чата (минимум 48 px) и прижат вправо; нижние виджеты упакованы первыми, чтобы не
  обрезаться при масштабировании.
- **Desktop:** сайдбар 292 px, основная колонка ≤ 1080 px с отступом `clamp(10px, 3vw, 42px)`;
  точки перелома 760 px (сайдбар свёрнут, подсказки скрыты, журнал в одну колонку) и 480 px (панель
  переносится, аватар скрыт, ответ на всю ширину).
- **Ритм:** шаг 4, рабочие значения 8 / 12 / 16 / 24.

## Elevation & Depth

Система плоская: глубину дают тональные ступени `background` → `panel` → `panel-2` → `raised`, тонкий
`stroke` там, где нужна граница поля или блока кода. Material-оттенок поверхности отключён
(`surfaceTintColor: transparent`, `elevation: 0`). Свечений нет нигде.

### Shadow Vocabulary
- **Тень композера Desktop** (`box-shadow: 0 10px 30px -12px #00000099`): единственная тень системы,
  только у композера в Gradio, чтобы отделить его от прокручиваемого чата. На Android и Windows
  композер держится тоном `panel-2` без тени.

### Named Rules
**The No Glow Rule.** Никаких светящихся ореолов, неоновых теней и цветных свечений — свет в этой
системе только у линии горизонта.

## Shapes

Мягкие скругления 6–22, без острых и без «таблеток» у карточек. Композер и пузырь пользователя —
20; у пузыря «хвост» 6 в правом нижнем углу (20/20/20/6). Поля ввода, кнопки и карточки примеров — 14;
блоки кода, плитки списков Android, кнопки Desktop — 12; строки списков Desktop — 10; логотип — плитка
9 (аватар 28) … 22 (72 на пустом чате) … 24 (вход). Чипы — капсула. Точка Pulse и аватар профиля —
круги. Drawer скруглён 20 по внешнему краю. Линия горизонта скруглена на свою высоту.
Windows (Tkinter) не умеет скругления: там те же роли передаются только тоном.

## Components

### Buttons
- **Форма:** мягкая (14 Android, 12 Desktop), Windows — прямоугольник ttk.
- **Основная:** сплошной фиолетовый, белый текст 600, высота ≥ 48 dp (46 в drawer, 52 на входе);
  Windows `Accent.TButton` padding 14×7.
- **Hover / pressed:** `violet-hover`; на Windows pressed #5B3BE6. Отключённая — `raised` с инеем.
- **Стоп:** на месте «Отправить», фон `raised`, текст/иконка коралл (Android — иней на `raised`).
- **Плоская:** прозрачная, лавандовый текст; hover — `panel` и снег.
- **Фокус:** Desktop — бирюзовое кольцо 2 px с отступом 2; Windows — `focuscolor` бирюза.

### Chips
- **Стиль:** `panel-2`, штрих-рамка, капсула, 13 px.
- **Состояние:** выбранный — `selected`; иконка «Интернет» бирюзовая при включении, иней при выключении.

### Cards / Containers
- **Скругление:** 14 (примеры), 12 (код).
- **Фон:** `panel` для карточек, `panel-2` для композера и развёрнутых деталей.
- **Тени:** нет (см. Elevation). **Рамка:** только у кода и полей. **Отступ:** 12–14.

### Inputs / Fields
- **Стиль:** заливка `panel-2`, рамка `stroke`, радиус 14, подсказка иней.
- **Фокус:** рамка лавандовая 1,6 (Android, Windows); Desktop-композер — рамка #3D3680.
- **Курсор:** лавандовый. Внутри композера рамок нет — его границу задаёт горизонт.

### Navigation
- Строки бесед и разделов: прозрачные, радиус 10–12, hover `raised`, выбрано `selected` со снегом.
  Избранное отмечено лавандой. Подписи групп — label инеем. Иконки Desktop — локальные SVG
  (`assets/icons/*.svg`, 18 px), Android — Material Icons rounded.

### Messages
- **Ответ Челси:** без подложки и рамки, логотип-аватар 28 (радиус 9) слева, Markdown, под ответом
  иконки-действия инеем 18 px (копировать, повторить, оценка).
- **Пузырь пользователя:** `user-bubble`, 20/20/20/6, справа, без рамки.
- **Источники:** линия `stroke` сверху, заголовок группы label-инеем, номер табличными цифрами,
  название лавандовой ссылкой, дата бирюзой справа.

### Aurora Horizon (signature)
Chelsy Pulse, нарисованный линией 3 px по верхнему краю композера (Android `AuroraBand`, Windows
`AuroraBand(Canvas)` из 64 сегментов, Desktop `#chelsy-compose::before`):
- **ready** — неподвижный градиент ≈35–40 %;
- **generating / checking** — градиент течёт, цикл 2,4 с linear;
- **searching** — бирюзовая волна пробегает, 1,6 с (Android 2,4 с);
- **syncing** — лавандовое дыхание 0,45–0,85;
- **offline** — ровный коралл 85 %.
Под reduced motion / `disableAnimations` линия неподвижна. Gradio дублирует каждое пользовательское
правило с префиксом `.gradio-container.gradio-container-6-5-1 .contain`, поэтому переопределения
состояний пишутся как `body:has(.pulse-x) #chelsy-compose#chelsy-compose::before`, а сила задаётся
альфой в цвете, не `opacity`.

### Chelsy Pulse dot
Точка 12–18 px в панели с расходящимся кольцом (1,6 с, `cubic-bezier(.16,1,.3,1)`) только в
рабочих состояниях; цвет: ready/searching бирюза, generating лаванда, offline коралл.

## Do's and Don'ts

### Do:
- **Do** держать градиент сияния только в линии горизонта (3 px у композера, 2 px неподвижная на пустом экране и входе).
- **Do** строить глубину тонами #0B0C20 → #11132B → #161937 → #1C2046, выбор — #2A2160.
- **Do** показывать даты бирюзой с табличными цифрами и без переноса.
- **Do** давать основному действию сплошной фиолетовый с белым текстом (5,15:1), а не фиолетовый текст на фоне.
- **Do** оставлять ответы Челси без подложки, с логотипом-аватаром; пользователя — пузырём #231D4F 20/20/20/6 справа.
- **Do** останавливать всё движение при «уменьшить движение» и анимировать только пока Челси работает.
- **Do** использовать стандартные контролы платформы и векторные иконки (Material Icons, локальные SVG).

### Don't:
- **Don't** заменять или перекрашивать брендовую палитру #0B0C20 / #6D4AFF / #A78BFA / #21D9DA и логотип.
- **Don't** добавлять свечения, неоновые тени и градиентные пятна на карточки, кнопки или фон.
- **Don't** отмечать активную строку цветной кромкой или цветной боковой рамкой.
- **Don't** использовать эмодзи или юникод-символы как иконки.
- **Don't** ставить основной текст фиолетовым #6D4AFF на ночном фоне (3,75:1).
- **Don't** подключать внешние шрифты или CDN на Desktop.

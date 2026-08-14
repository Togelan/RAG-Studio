# Исследование production-ready UI для RAG‑Studio

RAG‑Studio лучше позиционировать не как «ещё один AI dashboard», а как **инструмент управления корпоративным знанием**. Это меняет визуальную логику продукта: доверие к источникам, состояние данных, права доступа, предсказуемость операций и ясность причинно-следственных связей должны быть заметнее, чем сам факт использования AI. Такой подход хорошо согласуется с тем, как зрелые B2B-системы вроде GitHub Primer, Carbon и Atlassian строят интерфейсы вокруг ясной иерархии, системных токенов, доступности и функционального движения, а современные AI-продукты всё чаще делают источники и состояние AI-операции явной частью интерфейса. citeturn1search0turn1search14turn2search21turn11search13

Моя итоговая рекомендация — направление, которое ниже называется **Calm Knowledge Instrument / «спокойный инструмент работы со знанием»**: светлая редакционная основа, графитовые нейтрали, один насыщенный холодный акцент, тонкие границы, почти плоская архитектура приложения, выразительные, но редкие маркетинговые световые эффекты, первоклассная типографика и исключительно функциональная анимация.

## Визуальные направления

Ниже пять реально применимых направлений. Первые три подходят RAG‑Studio; четвёртое допустимо в небольших дозах; пятое полезно скорее как антипример.

| Направление | Как выглядит | Где особенно уместно | Риски | Оценка для RAG‑Studio |
|---|---|---|---|---|
| **Calm Knowledge Instrument** | Светлый или почти белый фон; графитовый текст; один cobalt/indigo-акцент; большие спокойные поля; 1px hairline-разделители; документная типографика; карточки почти без тени; редкие мягкие радиальные засветки только в маркетинге | Весь application shell, документы, чат с источниками, billing, настройки | Если сделать всё совершенно плоским, интерфейс может стать слишком «утилитарным» | **Лучший вариант** |
| **Technical Editorial** | Сочетание продуктовой UI-типографики с журнальной композицией: сильные заголовки, широкие отступы, выверенная длина строк, интерфейсные скриншоты вместо декоративных иллюстраций | Landing, pricing, onboarding, empty states | Слишком editorial-подача внутри таблиц и admin UI снижает плотность информации | **Очень хорошо как marketing layer** |
| **Precision Infrastructure** | Чуть более плотная компоновка; моноширинные вторичные значения; статусные метки; таблицы и метрики; минимум декоративности; акцент на системном состоянии | Ingestion, usage, audit/activity, настройки, workspace admin | Может напоминать DevOps-консоль и казаться холодным нетехническим пользователям | **Отлично для системных поверхностей** |
| **Soft Spatial / restrained glass** | Полупрозрачная верхняя навигация, очень мягкие фоновые световые пятна, отдельные floating layers | Hero landing, command menu, chatbot preview, launcher widget | `backdrop-filter` дороже обычных непрозрачных поверхностей; чрезмерная прозрачность ухудшает читаемость и создаёт «consumer app» ощущение. Browsers также предоставляют `prefers-reduced-transparency` именно потому, что прозрачность может мешать восприятию. citeturn0search1turn0search17 | **Только акцент** |
| **Neon AI spectacle** | Фиолетово-голубые mesh-gradient, светящиеся карточки, стекло на каждой поверхности, вращающиеся «knowledge network», sparkles, typewriter headline | Демо/эксперименты, но не корпоративная knowledge platform | Визуально связывает продукт с массовыми AI-лендингами; усложняет contrast, motion и GPU workload; отвлекает от происхождения данных и статусов | **Избегать** |

**Calm Knowledge Instrument** должен быть построен прежде всего на структуре. Хороший ориентир — недавнее обновление Linear: команда описывает идею так, что структура должна скорее «ощущаться», чем постоянно обозначаться разделителями; в обновлённом приложении были смягчены контрасты и края и уменьшен визуальный шум от разделителей. В марте 2026 Linear также переработал согласованность headers/navigation и визуально приглушил sidebar, чтобы основное содержимое получало больший приоритет. citeturn4search4turn4search12

Для RAG‑Studio это означает:

**Layout.** Пространство и выравнивание создают больше иерархии, чем рамки. Центральное рабочее содержимое — максимум примерно `1200–1440px`, но текстовые/формовые области существенно уже: `640–760px`; ответ AI — примерно `720–820px` или `68–76ch`.

**Цвет.** Не «AI-purple palette», а нейтральный рабочий canvas плюс **один основной брендовый hue**. Purple/cyan можно оставить вторичной частью едва заметной marketing illumination, но не semantic/UI-цветами.

**Типографика.** Интерфейс должен восприниматься ближе к хорошо спроектированному редактору или knowledge tool, чем к набору dashboard-карточек. Заголовки короткие и контрастные по размеру; body спокойный; identifiers, token counts, request IDs и технические значения допускают mono.

**Изображения.** Скриншоты реального продукта, citation previews, ingestion pipeline и widget deployment полезнее абстрактных 3D-мозгов, сфер и роботов. Landing Linear и системный подход Vercel/Geist демонстрируют, насколько много идентичности можно получить из типографики, пропорций и демонстрации самого продукта без декоративной перегрузки. citeturn4search0turn4search1turn4search29

**Borders и depth.** Постоянные surfaces различаются преимущественно фоном и 1px border; shadow появляется при **фактическом наложении**: dropdown, command palette, tooltip, dialog, floating widget.

**Motion.** Пользователь должен замечать прежде всего причинно-следственную связь: «нажал → изменилось», «файл индексируется → готов», «AI отвечает → можно остановить», а не само наличие анимации. Atlassian аналогично разделяет короткое interaction motion примерно `50–150ms` и более крупные переходы примерно `150–400ms`. citeturn2search21

**Что сразу сделает продукт generic или менее trustworthy:** ubiquitous purple/cyan glow; sparkles рядом с каждым AI-действием; десятки floating cards в hero; glassmorphism внутри форм и таблиц; 20px+ radius везде; neon status colors; каждый section landing с новым gradient; декоративный canvas/network за рабочим UI; giant statistic cards без реальной информационной ценности; автоиграющий typewriter; бесконечный shimmer; confetti после индексации документа; одинаковые «rounded rectangle + icon + title» для всей архитектуры приложения.

## Эффекты и детали высокого качества

Главный принцип: **эффект становится частью core visual language только тогда, когда он объясняет структуру или состояние**. Всё остальное должно иметь строгий бюджет.

| Эффект | Где работает | Где не использовать | A11y и mobile | Стоимость / реализация | Вердикт |
|---|---|---|---|---|---|
| **Restrained gradients** | Hero, CTA band, selected marketing illustration | Form backgrounds, таблицы, длинный текст | Текст должен сохранять WCAG contrast независимо от части градиента; на mobile уменьшить число слоёв | **Low**, если static CSS `linear-gradient`/`radial-gradient`; Tailwind arbitrary backgrounds | **Акцент** |
| **Gradient mesh** | Только большой hero backdrop | Application shell, chat body | Контент должен иметь независимую solid surface; mobile → 1–2 radial spots | **Low–medium** как несколько static radial gradients; не анимировать background-position | **Редко** |
| **Noise / grain** | Marketing background, крупная branded panel | Forms, chat messages, таблицы | Не должен снижать читаемость; убрать на low-end/mobile | **Low**: tiny repeating AVIF/PNG, opacity `1–2%`; не animated SVG turbulence | **Редко** |
| **Ambient glow** | За product mockup, CTA section | За таблицами, composer, form controls | Не использовать как единственный indicator; mobile можно сделать static или отключить | Static radial gradient дешёв; большие анимированные blur/filter слои существенно хуже | **Акцент** |
| **Glass / translucency** | Sticky landing nav, отдельный floating overlay | Основные cards, settings, pricing copy, tables | Нужна непрозрачная fallback surface; учитывать `prefers-reduced-transparency`. citeturn0search17 | **Medium–high**: `backdrop-filter` может быть заметно дороже и требует тестирования; создаёт отдельные rendering/stacking considerations. citeturn0search1turn0search14 | **Очень редко** |
| **Layered card depth** | Popovers, command palette, dialogs; лёгкая surface hierarchy | Не давать shadow каждой dashboard-card | Shadow не заменяет border/semantic distinction | **Low** static shadow; CSS variables + Tailwind shadows | **Core** |
| **Hairline borders** | Практически весь application UI | Не превращать страницу в сетку из рамок | Meaningful control boundary должен оставаться видимым; focus ring отдельный | **Очень low**; semantic border tokens | **Core** |
| **Highlighted edges** | Selected card, pricing recommendation, active chatbot | Все карточки сразу | Цвет не единственный selected-state | **Low**: 1px border + subtle tinted background; иногда inset highlight | **Core, умеренно** |
| **Static grid / dot field** | Landing hero, developer/deployment section | Dashboard / settings / chat | Decorative only → `aria-hidden`; mobile значительно приглушить | **Low** CSS/SVG background | **Акцент** |
| **Animated grid / knowledge network** | Почти нигде | Весь application shell и mobile | Отключать при reduced motion; постоянное движение отвлекает | Большие repaint/composite layers могут стоить дорого; для performant animation лучше `transform`/`opacity`, а не layout/paint properties. citeturn0search5turn0search13 | **Избегать** |
| **Aurora / light spots** | Один branded hero | Dashboard, auth form, widget по умолчанию | Reduced motion → static; mobile → один spot | Static **low**; несколько blur-анимаций **medium/high** | **Редко** |
| **Gradient headline** | Одно ключевое слово в H1 | Labels, metrics, chat output | Solid-color fallback; нельзя жертвовать contrast | **Low**: `background-clip:text` | **Редко** |
| **Masked text/image reveal** | Marketing storytelling | App UI и основной copy | Контент обязан существовать без animation | CSS mask/opacity; не делать критичный контент зависимым от observer | **Редко** |
| **Scroll reveal** | Landing sections | Dashboard, таблицы, settings | Без JS контент видим; `prefers-reduced-motion` → без translate | IntersectionObserver + `opacity`/`transform`; **low** при небольшом числе элементов | **Акцент** |
| **Parallax** | В лучшем случае маленький декоративный hero layer | Application UI, mobile, onboarding | Полностью отключать при reduced motion; может вызывать дискомфорт у motion-sensitive пользователей. citeturn0search2turn0search6 | Scroll-linked work легко становится дорогим | **Избегать по умолчанию** |
| **Skeleton states** | Initial table/list/chat history load | Долгая indexing job с известным состоянием | Не оставлять бесконечный shimmer; reduced motion → static | shadcn имеет базовый Skeleton; Carbon рекомендует skeleton для начальной загрузки, а не как универсальный long-running state. citeturn5search9turn6search11 | **Core** |
| **AI streaming** | Ответ ассистента | Никогда не симулировать stream статичного ответа ради театральности | Не `aria-live` на каждый token; объявлять состояние и completion менее шумно | React buffered chunks + SSE/WebSocket backend; Carbon AI Chat поддерживает streamed responses и stop behavior. citeturn6search0turn6search4turn6search8 | **Core** |
| **Ingestion progress** | Upload/index pipeline | Не показывать fake 73%, если backend не знает реального прогресса | `role=progressbar`, `aria-valuemin/max/now` для determinate; текстовое имя stage. citeturn6search14turn6search19 | **Low**: CSS width/transform + backend events | **Core** |
| **Success state** | File ready, saved config, invite sent | Не перекрывать workflow модалкой «Success!» | Icon + text + color; no color-only meaning | **Low**; inline state / toast | **Core** |
| **Empty state** | No docs, no chatbot, no invoices/results | Не использовать generic astronaut/AI illustration повсюду | Заголовок объясняет ситуацию, CTA доступен с клавиатуры | Carbon различает first-use/no-data/unavailable empty-state scenarios. citeturn6search3 | **Core** |
| **Hover** | Rows, buttons, clickable cards | Не скрывать необходимые actions исключительно до hover | Каждому hover-сигналу нужен keyboard/focus equivalent; hover-disclosed content требует осторожности. citeturn3search37 | **Очень low** | **Core** |
| **Command palette** | Workspace navigation, quick-create, docs/chatbot search | Не делать единственным способом найти функцию | Visible trigger + `⌘K`/`Ctrl+K`; full keyboard navigation | shadcn Command прямо предназначен для command menu/search и shortcut affordances. citeturn5search13turn5search1 | **Core power feature** |
| **Button microinteraction** | Hover/active/loading | Не использовать bounce | Reduced motion → instant state | `opacity`, `transform: scale(.98)` `80–120ms`; compositor-friendly. citeturn0search28 | **Core** |
| **Toggle microinteraction** | Settings switches | Не задерживать изменение value | Accessible checked state, keyboard | Thumb translation `120–160ms`; reduced → instant | **Core** |
| **Tooltip** | Неподписанная иконка, shortcut clarification | Не помещать в tooltip обязательные инструкции | Trigger должен работать с focus; tooltip не должен содержать необходимые интерактивные controls. Atlassian и Radix отдельно предусматривают keyboard focus behavior. citeturn2search1turn2search4turn5search7 | **Low** | **Core, по необходимости** |
| **Toast** | Background success, invite sent, transient system event | Validation errors, critical decisions, long explanation | Не единственный способ узнать важный результат; статус должен объявляться assistive technology. citeturn9search2 | **Low** | **Core** |

Особенно важно различать **skeleton** и **progress**. Skeleton отвечает на вопрос «как будет выглядеть ещё не полученный контент», а progress отвечает на вопрос «что система сейчас делает». Для ingestion второй вариант значительно честнее. Carbon аналогично имеет отдельные patterns для skeleton/loading, inline loading и progress. citeturn6search2turn6search17turn6search14

Для AI-response не стоит имитировать посимвольную печать. Ответ следует показывать по мере поступления реальных chunks; button **Stop generating** появляется сразу после начала операции. Carbon AI Chat прямо поддерживает streaming и немедленную остановку streaming response, а OpenAI в корпоративном knowledge experience делает цитируемые источники явной частью ответа — оба паттерна особенно релевантны RAG-продукту. citeturn6search4turn6search16turn11search13

В Tailwind motion должен уважать системную настройку пользователя через `motion-safe:` / `motion-reduce:`; Tailwind документирует эти variants, а `prefers-reduced-motion` отражает OS-level preference пользователя. citeturn0search2turn0search3turn0search18

## Рекомендации по страницам

| Surface | Информационная иерархия | Visual / motion | States | Desktop → mobile | Главная цель |
|---|---|---|---|---|---|
| **Landing** | Value proposition → CTA/demo → trust/proof → «как работает» → citations/RAG demo → permissions/security → deployment/widget → final CTA | Один ambient radial gradient, едва заметный grid, real product UI cards. Section reveal `opacity + 8–16px translate`, без autoplay theatrics | Product demo имеет реалистичные loading/error states; landing не должен зависеть от animation | Desktop 2-column hero; mobile single column, screenshot/demo под CTA, nav → sheet | **Довести квалифицированного B2B-пользователя до trial/demo** |
| **Pricing** | Billing cadence → tiers → included usage → overage/limits → feature comparison → FAQ/contact | Почти полностью flat. Recommended plan: subtle tinted surface или accent top edge, не glowing card | Loading billing config; unavailable enterprise action ясно объясняется | Plan cards stack; comparison table → grouped feature sections/accordion | **Позволить выбрать тариф без неясности стоимости** |
| **Sign-up / sign-in** | Brand → clear auth intent → email/SSO → divider → policy/help; workspace selection после identity, если нужно | Узкая `420–460px` surface; практически никаких эффектов; optional quiet branded background только desktop | Inline validation, busy button, auth provider error, verification, org selection | На mobile form становится основной page surface, без декоративной side panel | **Минимум трения и максимум доверия** |
| **Workspace dashboard** | Workspace identity → urgent status → primary actions → ingestion/chatbot/usage summaries → activity | Flat shell, surface layers, hairlines, максимум один содержательный chart | Skeleton initial load; empty onboarding; degraded source connection; quota warning | Sidebar → drawer/bottom navigation; cards → one column | **За несколько секунд понять состояние workspace и следующий шаг** |
| **Document ingestion** | Drop/select → upload queue → pipeline stages → per-file errors → final indexed documents | Real progress bars, status badges, restrained row transitions | queued → uploading → extracting → chunking → indexing → ready / failed; indeterminate, когда % неизвестен | Table-like rows → stacked file rows; upload CTA остаётся крупным | **Создать уверенность, что знания успешно попадают в систему** |
| **Chatbot management** | Chatbots list → status/sources/usage → edit → config tabs → preview → deploy | Selected-row surface; live preview; никаких декоративных dashboard tiles | Empty “Create first chatbot”; unsaved; invalid config; publish success | Master/detail становится list → separate detail route; preview → fullscreen sheet | **Быстро найти, настроить и опубликовать bot** |
| **AI chat + citations** | Conversation → current answer → inline citation anchors → source inspector → composer | Real streaming, subtle generation indicator, no fake typing; citations интерактивны | retrieving → generating → complete; stop; retry; partial failure; citation unavailable | Answer `68–76ch`; desktop source drawer `320–380px`; mobile sources → bottom sheet | **Пользователь должен быстро проверить, почему ответу можно доверять** |
| **Billing & usage** | Current plan → current period usage → limits/forecast → breakdown → invoices/payment | Простые line/bar charts; no decorative gradient data fills | Near-limit warning, payment failed, zero usage, invoice loading | Cards vertically; data table → prioritized rows/details | **Не допускать неожиданных ограничений или расходов** |
| **Settings** | Section nav → one task-oriented form at a time → save/status; Danger Zone last | Практически no visual effects; dialogs только для high-impact/destructive action | dirty, saving, saved, validation, conflict, permission denied | Section nav → index screen/back navigation | **Сделать admin changes безопасными и предсказуемыми** |
| **Shadow-DOM widget** | Header/identity → messages/citations → composer → footer attribution/actions | Минимальный branded surface; no ambient effect by default; launcher only gets tiny hover/press | connecting, empty, generating, stop, error/retry, offline | ~`380×620px` desktop; около `<480px` лучше `8px` inset/fullscreen `100dvh` experience | **Надёжно работать на любой host-site и не выглядеть чужеродно** |

**Landing.** Здесь RAG‑Studio можно позволить больше визуальной индивидуальности, но distinctive layer должен служить демонстрации продукта. Хорошая композиция: слева один очень ясный promise вроде «Answers your team can verify», справа не абстрактная 3D-графика, а реальный mini-chat с раскрытой citation card и одним документом, из которого взят фрагмент. Linear строит свой landing вокруг самой рабочей системы и идеи speed/focus, а Vercel показывает, насколько далеко можно зайти в брендировании через системные typography/layout primitives вместо декоративного перегруза. citeturn4search0turn4search1

**Pricing.** Pricing — не место демонстрировать всю графическую систему. Полезнее использовать визуальную тишину, чтобы различия между планами, usage и limits были сканируемыми. Текущий Stripe Pricing — хороший объект изучения именно как пример большого количества коммерческой информации, организованной вокруг продукта и модели оплаты, а не вокруг декоративной анимации. citeturn4search2

**Authentication.** Multi-tenant model должен стать частью workflow: пользователь сначала доказывает identity, затем при необходимости выбирает organization/workspace. WorkOS AuthKit показывает production-подход, в котором hosted flow обрабатывает sign-up/sign-in/password/provider edge cases, а branding включает цвет, logo, layout, radius, dark mode и legal links; Clerk отдельно моделирует organization selection как session task. Это полезные архитектурные ориентиры, даже если RAG‑Studio реализует собственный UI. citeturn12search8turn12search2turn12search6

**Dashboard.** Не начинать с четырёх одинаковых KPI cards. Первая зона должна отвечать на операционные вопросы: «Все ли источники проиндексированы?», «Есть ли chatbot с проблемой?», «Каково usage относительно limit?», «Что изменилось недавно?». Primer рекомендует спокойную, незагромождённую layout hierarchy и перестройку многоколонных схем в mobile-friendly patterns, а не механическое сжатие desktop UI. citeturn1search14

**Document ingestion.** Показывать pipeline человеческими словами. Например:

`Queued → Uploading → Extracting text → Preparing chunks → Indexing → Ready`

Если сервер знает только текущий stage, показывать stage, но **не выдуманный percentage**. Если известны байты upload — показывать determinate upload progress; если indexing duration не оценивается — indeterminate progress с явным текстом этапа. Failed row остаётся на месте и получает причину + `Retry`, а не исчезает в toast.

**Chatbot configuration.** Лучший desktop pattern — содержимое configuration в центре и необязательный live preview справа. Вкладки лучше отражают mental model продукта: `General`, `Knowledge`, `Instructions`, `Appearance`, `Deploy`. Не делать каждую setting карточкой: Primer подчёркивает снижение effort/cognitive load в forms, что обычно означает последовательные группы полей и ясные labels, а не коллекцию декоративных containers. citeturn1search9

**Chat.** Citation должна быть не decoration после ответа, а частью answer model. Inline marker `[1]` или compact source chip открывает right drawer / mobile bottom sheet с `source title → snippet → location → Open source`. Carbon AI Chat имеет отдельную модель conversational-search responses с RAG citations, а OpenAI Company Knowledge подчёркивает clear citations к корпоративным источникам. citeturn6search16turn6search21turn11search13

В streaming-chat следует предотвращать два раздражителя. Во-первых, auto-scroll выполняется только пока пользователь находится у нижней границы conversation; просмотр старого текста не должен «оттягиваться» вниз. Во-вторых, citation/source panel не должен перестраивать ширину текста в середине generation: на desktop лучше заранее резервировать predictable layout или показывать overlay drawer.

**Billing.** Здесь графики имеют смысл только там, где показывают trend или путь к limit. Одна цифра `42 351 messages` не требует chart. Carbon Data Visualization формирует categorical palettes так, чтобы соседние значения оставались различимыми; принцип стоит перенести в RAG‑Studio, но количество одновременно используемых серий лучше держать очень небольшим. citeturn1search16

**Shadow-DOM widget.** Это отдельная mini-design system. Shadow DOM изолирует внутреннее дерево и styles от host document, а CSS custom properties по умолчанию наследуются, что удобно для ограниченного API брендирования. `::part()` позволяет намеренно раскрыть лишь выбранные styling hooks. citeturn3search0turn3search4turn3search34

Для RAG‑Studio разумный public API:

```css
rag-studio-chat {
  --rag-accent: #4156d9;
  --rag-surface: #ffffff;
  --rag-text: #101418;
  --rag-radius: 12px;
  --rag-font-family: Inter, system-ui, sans-serif;
}
```

Не следует разрешать host-site переопределять десятки внутренних spacing/status variables: это ломает визуальные и accessibility-инварианты.

Особенно важный implementation detail: Radix portals по умолчанию рендерят содержимое в `document.body`, но API позволяет указать собственный `container`. Поэтому Dialog, Dropdown, Popover и Tooltip внутри Shadow DOM нужно portal-ить **в элемент внутри shadow root**, иначе overlay может выйти из scoped styles widget. citeturn15search1turn15search0turn15search5

## Дизайн-система

Систему стоит строить в два слоя: **primitive tokens → semantic tokens**. Такой подход применяется, например, в Fluent и Atlassian: базовые значения отделены от смысловых aliases, что позволяет менять тему без переписывания component-level styles. Carbon также строит light/dark themes из semantic token layers. citeturn2search5turn2search3turn1search11

**Предлагаемая light palette:**

| Token | Значение | Роль |
|---|---:|---|
| `--bg` | `#F7F8FA` | Canvas |
| `--surface` | `#FFFFFF` | Main surface |
| `--surface-subtle` | `#F1F3F5` | Secondary layer |
| `--text` | `#101418` | Primary text |
| `--text-muted` | `#5B6672` | Secondary text |
| `--border-subtle` | `#DDE2E7` | Необязательные structural separators |
| `--border-control` | `#7A8794` | Значимые control boundaries |
| `--accent` | `#4156D9` | Interactive/brand |
| `--success` | `#16794A` | Ready/positive |
| `--warning` | `#8A5A00` | Attention |
| `--danger` | `#B42318` | Error/destructive |
| `--info` | `#2459C3` | Informational |

Расчётные contrast ratios предложенных пар: `#101418`/white ≈ **18.5:1**, `#5B6672`/white ≈ **5.85:1**, white/`#4156D9` ≈ **5.90:1**, `#16794A`/white ≈ **5.43:1**, `#8A5A00`/white ≈ **5.93:1**, `#B42318`/white ≈ **6.57:1**. Это даёт хороший запас относительно WCAG AA, где обычный текст требует как минимум `4.5:1`, а large text — `3:1`; W3C подчёркивает, что пороговые ratios не следует округлять вверх. citeturn8search0

`--border-subtle` намеренно значительно светлее: это **не** цвет для единственной визуальной границы essential control. Для input/button outline, где boundary несёт значение, следует использовать более сильный control border либо дополнительную surface distinction. Цвет никогда не должен быть единственным способом сообщить ready/error/warning.

**Dark mode рекомендован**, но не должен быть главным visual identity продукта:

```text
bg              #0D1014
surface         #13181D
surface-subtle  #192027
text            #F5F7FA
text-muted      #A6B0BA
border          #2A333C
accent          #8EA0FF
```

В dark UI меньше полагаться на shadows и больше — на surface steps и borders. Carbon использует аналогичную layer-based модель в light/dark themes. citeturn1search4turn1search11

Theme preference лучше хранить per user: `System / Light / Dark`. Widget получает собственную настройку `auto | light | dark`, потому что theme host page и theme account не обязательно совпадают.

**Typography.** Безопасная production-база для multilingual B2B: `Inter Variable` для интерфейса и `ui-monospace`/качественный mono для IDs, code и технических значений. Variable fonts позволяют одному font resource покрывать диапазон axes/weights и потенциально заменять несколько static files; font delivery всё равно необходимо оптимизировать через WOFF2/subsetting и разумную `font-display` стратегию. citeturn7search1turn7search0turn7search4

Рекомендуемая шкала:

| Роль | Desktop | Mobile | Weight / line-height |
|---|---:|---:|---|
| Marketing H1 | `56–72px` | `38–44px` | 600–650 / `1.02–1.10` |
| H1 app | `28–32px` | `26–28px` | 600 / `1.15` |
| H2 | `22–24px` | `20–22px` | 600 / `1.2` |
| H3 | `17–18px` | `17–18px` | 600 / `1.3` |
| Body large | `16–18px` | `16–17px` | 400–450 / `1.5` |
| UI body | `14–15px` | `14–16px` | 400–500 / `1.45` |
| Metadata | `12–13px` | `12–13px` | 450–500 / `1.4` |
| Mono data | `12–14px` | `12–14px` | 450 / `1.4` |

Не превращать `12px` в стандартный body size. Atlassian, например, рекомендует для long-form content не менее `16px`, сохраняя мелкие размеры для вторичной информации. citeturn2search9

**Spacing.** Базовый quantum `4px`, основной rhythm `8px`:

`4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96`.

Это близко к зрелым системам: Carbon использует систематическую шкалу от 2/4/8 до крупных layout spacing, Atlassian также опирается на 8px-centric spacing scale. citeturn1search12turn2search15

**Radius.**

| Element | Radius |
|---|---:|
| dense controls | `6px` |
| button/input | `8px` |
| card/popover | `10–12px` |
| modal / marketing panel | `14–16px` |
| badge/avatar/pill | `999px` только когда форма действительно pill/circle |

Это важный anti-generic выбор: не использовать `rounded-2xl`/`rounded-3xl` без разбора.

**Elevation.**

```css
--shadow-0: none;
--shadow-1: 0 1px 2px rgb(16 24 40 / 0.06);
--shadow-2:
  0 1px 2px rgb(16 24 40 / 0.05),
  0 8px 24px rgb(16 24 40 / 0.08);
--shadow-3:
  0 4px 8px rgb(16 24 40 / 0.06),
  0 20px 48px rgb(16 24 40 / 0.12);
```

`shadow-0`: normal cards. `shadow-1`: sticky/floating local control. `shadow-2`: menu/popover. `shadow-3`: dialog/command palette. Elevation как иерархия, а не декор, соответствует подходу Fluent. citeturn2search8

**Focus.** `2px` outline/ring + `2px` offset, никогда не удалять outline без полноценной альтернативы. `:focus-visible` предпочтительнее постоянного ring для pointer clicks; W3C требует видимого keyboard focus для Focus Visible. citeturn9search0turn3search17

**Icons.** Lucide:

- `16px` для compact table actions;
- `18px` default;
- `20px` toolbar/navigation;
- `24px` marketing/empty state;
- stroke около `1.75–2`.

Icon-only control всегда имеет accessible name, а когда смысл не очевиден — tooltip. Не использовать sparkle icon как универсальную метку AI. Если action действительно AI-driven, лучше текст `Generate with AI`/`Improve with AI` и конкретное действие. Carbon AI guidance отдельно рекомендует AI label как сигнал использования AI и путь к transparency, а не как декоративную кнопку. citeturn5search8

**Forms.** Label всегда остаётся видимым; placeholder не заменяет label. Field stack: label → control → optional help/error. Default heights `36–40px` desktop и effective touch surface `44–48px` mobile. Ошибка располагается рядом с полем и при submit может дублироваться в summary для длинной формы.

**Cards.** Карточка нужна только когда существует реальная группировка. Она не должна быть default wrapper для каждого двухстрочного блока. Default card: white/surface, 1px subtle border, radius 12, no shadow.

**Tables.** На desktop использовать semantic `<table>` для настоящих tabular datasets. Carbon и Vercel Design System имеют отдельные table primitives; это хороший сигнал не превращать таблицы в набор `div` ради styling convenience. citeturn6search7turn4search25

На mobile выбирать один из трёх вариантов: оставить только ключевые columns; превратить row в structured record; открыть подробности row на отдельном экране. Horizontal scrolling допустим для истинно табличных данных, но не должен быть незаметным единственным способом найти core actions; Atlassian отдельно отмечает accessibility-проблемы poorly handled horizontally scrolling tables. citeturn2search10

**Status badges.** Compact, low-saturation tint + icon optional + text mandatory:

`Ready`, `Indexing`, `Draft`, `Paused`, `Failed`, `Limit near`.

Badge не должен становиться яркой capsule-конфетти. Atlassian Lozenge применяется именно как компактное обозначение состояния. citeturn2search28

**Charts.** Основные типы — line, bar, area; pie/donut только когда proportions действительно являются задачей. Не более примерно пяти-шести categorical hues. Critical metric всегда доступен также текстом/таблицей. `shadcn/ui` Chart построен поверх Recharts и поддерживает `accessibilityLayer`, что делает его разумной стартовой точкой, но accessibility не заканчивается включением одного prop. citeturn5search15

**Dialogs.** Для reversible action — обычный Dialog; для destructive/high-impact confirmation — AlertDialog. Radix управляет focus, keyboard interaction и announcements через Title/Description, если primitive используется правильно. citeturn5search3turn5search14

**Toasts.** Не более одного-двух одновременно; success обычно `3–5s`, error остаётся дольше или требует dismiss, если сообщение нельзя безопасно потерять. Ошибка формы не должна существовать только как toast.

**Tooltips.** Только для supplementary information. Не помещать туда формы, links и критичные instructions. citeturn2search4turn5search7

**Responsive breakpoints.** Можно сохранить Tailwind defaults — `sm 640`, `md 768`, `lg 1024`, `xl 1280`, `2xl 1536` — но **не проектировать компоненты “под breakpoint” там, где container width даёт более правильный ответ**. Текущая документация Tailwind определяет именно эти defaults. citeturn13search0

Внутреннее правило RAG‑Studio:

```text
360–479   phone compact
480–639   phone wide
640–767   small/tablet
768–1023  tablet / compact app
1024+     desktop application shell
1280+     comfortable desktop
```

Application sidebar разумно превращать в persistent navigation только около `lg`; widget вообще должен реагировать на собственный container/viewport, а не на breakpoints host application.

## Система движения и взаимодействий

Motion system должен быть маленьким и предсказуемым. Не заводить по custom easing для каждого component.

**Предлагаемые motion tokens:**

| Token | Duration | Где |
|---|---:|---|
| `--motion-instant` | `0ms` | state that should not visually travel |
| `--motion-press` | `80ms` | button press |
| `--motion-fast` | `120ms` | hover, color, icon |
| `--motion-control` | `160ms` | toggle, selected state |
| `--motion-overlay` | `180–220ms` | popover, menu, tooltip |
| `--motion-dialog` | `220–260ms` | modal, sheet |
| `--motion-layout` | `240–300ms` | small accordion/layout reveal |
| practical upper bound | `400ms` | только редкая крупная transition |

Это находится в том же функциональном диапазоне, что и актуальная motion-система Atlassian: короткие interactions `50–150ms`, transitions `150–400ms`. Atlassian также публикует несколько конкретных cubic-bezier curves для entrances, exits и modal/repositioning. citeturn2search21

У RAG‑Studio можно стандартизировать:

```css
--ease-enter: cubic-bezier(.4, 1, .6, 1);
--ease-emphasized-enter: cubic-bezier(0, .4, 0, 1);
--ease-layout: cubic-bezier(.4, 0, 0, 1);
--ease-exit: cubic-bezier(.6, 0, .8, .6);
```

**Анимировать:** hover/pressed/focus supporting states; toggle thumb; menu/popover/dialog appearance; small disclosure; row insertion/removal, когда нужно показать причинность; progress; status transition; AI streaming; source panel appearance.

**Оставлять instant:** текст после edit; checkbox value/selection semantics; route state в случаях, когда animation ничего не объясняет; error visibility после validation; permission changes; stop-generation command; destructive result. Сам semantic state меняется сразу, даже если его визуальное оформление мягко догоняет состояние.

Для крупного navigation transition лучше использовать очень короткий fade, а не slide всего приложения. Fluent отдельно рекомендует quick fade для top-level page transition вместо больших движущихся/sliding surface transitions. citeturn2search17

**Implementation principle:** для плавной motion предпочтительны `transform` и `opacity`; animation `width`, `height`, `top`, `left` и прочих layout-triggering properties может заставлять browser повторно выполнять layout/paint. citeturn0search5turn0search13turn0search28

**AI responsiveness без fake waiting.**

После отправки prompt:

1. Сообщение пользователя появляется **сразу**, composer очищается, send становится `Stop`.
2. Пока идёт retrieval, короткий unobtrusive status может сказать `Searching 12 sources…`.
3. Как только приходит реальный response chunk, placeholder исчезает и начинается настоящий streaming.
4. Не вводить искусственный `600ms` timeout «для ощущения AI».
5. Source metadata можно показать до полного answer, если оно уже стабильно получено.
6. `Stop` прекращает backend generation максимально быстро.
7. После completion появляются secondary actions: `Copy`, feedback, `Regenerate`.
8. Если streaming оборвался, partial answer сохраняется с `Response interrupted · Retry`, а не исчезает.

Carbon AI Chat поддерживает как streamed, так и non-streamed response modes, chunk-based updates и stop streaming, поэтому этот interaction model не требует экзотической frontend-архитектуры. citeturn6search9turn6search8turn6search4

Для screen reader **не нужно объявлять каждый token**. W3C Status Messages предусматривает programmatic announcements статуса без перемещения focus, но предупреждает против чрезмерно разговорчивых live regions. Лучше объявить `Generating answer`, затем `Answer complete`, а ошибки — отдельно. citeturn9search2

**Loading behavior.** Skeleton только там, где известна будущая геометрия. Для action после click можно использовать inline spinner/button state. Для долгой background job — persistent status/progress, который не блокирует остальное приложение. Carbon аналогично отделяет full loading, inline loading и progress patterns. citeturn6search6turn6search17turn6search14

**Reduced motion.**

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto;
  }

  .decorative-motion {
    animation: none;
    transform: none;
  }
}
```

Не обязательно обнулять абсолютно любую transition: короткий opacity change может сохранять context без значимой пространственной motion. Но parallax, animated aurora, translate/scale reveal и auto-animated decorative backgrounds следует убрать. MDN определяет `prefers-reduced-motion` как механизм обнаружения системной настройки, предназначенной для минимизации несущественного движения. citeturn0search2

В Tailwind:

```tsx
<div
  className="
    transition-[opacity,transform] duration-150
    motion-safe:translate-y-0
    motion-reduce:transform-none
    motion-reduce:transition-none
  "
/>
```

Tailwind предоставляет `motion-safe` и `motion-reduce` variants именно для этого применения. citeturn0search3turn0search18

## Доступность и производительность

Для продукта, в который компании загружают внутренние документы, accessibility и performance должны считаться частью trust layer, а не пострелизной полировкой.

**WCAG AA — baseline, не цель “когда-нибудь”.** Для normal text нужен contrast минимум `4.5:1`, для large text — `3:1`. UI states нельзя кодировать только цветом. citeturn8search0turn0search0

**Keyboard полностью покрывает core workflow.** Sidebar, command menu, data rows с actions, document uploader, dialogs, source citations, chat controls и widget должны быть usable без pointer. DOM order должен соответствовать визуальной/логической последовательности; произвольные положительные `tabindex` — плохой способ исправлять ошибочную структуру. citeturn7search14turn5search20

**Focus всегда видим.** Не `outline-none` без replacement. W3C Focus Visible требует keyboard focus indicator; `:focus-visible` позволяет дать strong ring клавиатуре, не создавая лишнего ring после каждого mouse click. citeturn9search0turn3search17

**Screen reader semantics.** Icon buttons получают accessible name; dialogs — Title/Description; loading/progress — semantic states; form errors связаны с input; table остаётся table; changing background status можно объявлять live region без перемещения focus. Radix реализует существенную часть focus/keyboard/ARIA mechanics в primitives, но корректные labels и product semantics остаются ответственностью RAG‑Studio. citeturn5search16turn5search20turn9search2

**Touch targets.** WCAG 2.2 Target Size Minimum на AA задаёт минимум `24×24 CSS px` с определёнными исключениями/spacing conditions. Для production SaaS на телефоне разумнее установить свой более удобный минимум **44×44px effective hit area** для главных controls и launcher. citeturn8search1

**360px — реальный minimum width.** Ни одна core surface не должна требовать horizontal viewport scrolling. На `360px`:

- sidebar отсутствует как fixed column;
- tables переосмысляются;
- dialog не шире viewport минус `16–24px`;
- composer не переполняется из-за icon buttons;
- breadcrumbs сокращаются;
- long email/domain/filename используют safe wrapping/truncation с доступом к полному значению;
- widget занимает почти всю ширину;
- chart legend перестраивается;
- code/URL может локально scroll-иться, но не расширяет page.

Primer прямо рассматривает responsive behavior как неотъемлемую часть доступного UI и рекомендует сохранять функциональность при перестройке многоколонного layout. citeturn1search5turn1search14

**Performance budget для эффектов.** Не использовать WebGL/canvas/video только ради атмосферы hero. Большой autoplay video на первом viewport одновременно увеличивает network/rendering budget и ничего не добавляет к пониманию knowledge workflow. CSS/SVG/static screenshot почти всегда достаточны.

Для continuous animation использовать compositor-friendly `transform` и `opacity`; свойства, провоцирующие layout/paint, требуют большей работы браузера. citeturn0search5turn0search31

`backdrop-filter: blur()` применять максимум на небольшом количестве layers. web.dev отдельно рекомендует тестировать performance backdrop-filter и предоставлять fallback, а MDN описывает его как фильтрацию содержимого позади элемента — то есть это принципиально более сложная операция, чем обычная solid background. citeturn0search1turn0search14

Не разбрасывать `will-change` по всему UI. Это hint браузеру для потенциальной оптимизации, а не универсальная директива «сделать GPU быстрее». citeturn0search26

**Font performance.** Предпочтительны WOFF2, subset нужных языков/glyph ranges и небольшое количество реально используемых weights. Variable font может заменить несколько static font files; выбор self-hosting против CDN всё равно надо проверять по фактической инфраструктуре и caching, а не считать self-host автоматически быстрее. citeturn7search0turn7search1

**Widget performance строже основного приложения.** Он загружается на чужой сайт, где RAG‑Studio не контролирует CPU, CSS, framework и network budget. Поэтому:

- отдельный небольшой bundle;
- lazy-load chat UI после interaction с launcher, если business requirements позволяют;
- launcher не требует React-heavy animation;
- никаких remote background videos;
- никаких WebGL/network animations;
- font по умолчанию system stack либо очень маленький optional resource;
- Shadow DOM styles self-contained;
- не предполагать наличие Tailwind CSS на host page.

Carbon Web Components — полезный референс для такой архитектуры, потому что библиотека сознательно строится на Custom Elements и Shadow DOM v1. citeturn6search28

**Минимальный QA gate перед release:** keyboard-only walkthrough; screen-reader smoke test; `prefers-reduced-motion`; light/dark contrast; zoom `200%`; widths `360/390/768/1024/1440`; long localization strings; 20+ character workspace names; very long filenames; throttled CPU/network; failed SSE/stream; upload cancellation; expired authentication; host page with hostile/reset CSS around the widget.

## Анализ референсов

Ниже не предлагается визуально копировать продукты. Полезны **принципы, степень сдержанности и конкретные interaction architectures**.

| Reference | Что изучить | Почему работает / как адаптировать | Класс |
|---|---|---|---|
| **Linear — 2026 Design Refresh** — [linear.app/now/behind-the-latest-design-refresh](https://linear.app/now/behind-the-latest-design-refresh) | Смягчение separators, более спокойные surfaces, идея «structure felt rather than seen» | Для RAG‑Studio уменьшить количество boxed cards и использовать spacing/surface hierarchy; не копировать цветовую палитру или exact sidebar | **Application-shell inspiration** citeturn4search4 |
| **Linear product** — [linear.app](https://linear.app/) | Product-first hero, сильная типографическая иерархия, controlled animation | Landing RAG‑Studio должен показывать реальные citations/ingestion/chatbot UI вместо generic AI imagery | **Landing-page inspiration** citeturn4search0 |
| **Linear navigation updates** — [linear.app/changelog](https://linear.app/changelog) | Consistent headers/navigation/view controls; sidebar визуально отступает от content | Сделать workspace/content primary, chrome secondary; не подсвечивать всю навигацию одинаково | **Application-shell inspiration** citeturn4search12 |
| **Vercel Design / Geist** — [vercel.com/design](https://vercel.com/design) | Typography, spacing, token-level consistency, высокая polish взаимодействий | Взять дисциплину: небольшой набор primitives и сильная consistency; не клонировать black-and-white Vercel aesthetic | **Application-shell / landing inspiration** citeturn4search1turn4search9 |
| **GitHub Primer Layout** — [primer.style/product/getting-started/foundations/layout](https://primer.style/product/getting-started/foundations/layout/) | Calm, uncluttered layout, familiar mental models, responsive decomposition | Отличный ориентир для workspace, documents и admin navigation; индивидуальность добавить через typography/color/detail, а не необычную навигацию | **Dashboard inspiration** citeturn1search14 |
| **Atlassian Motion** — [atlassian.design/foundations/motion](https://atlassian.design/foundations/motion/) | Разделение microinteraction и transition durations, практичные easing curves | Свести motion RAG‑Studio к небольшому token set; не изобретать разные spring animations на компонент | **Motion inspiration** citeturn2search21 |
| **Carbon AI Chat** — [chat.carbondesignsystem.com](https://chat.carbondesignsystem.com/) | Streaming/non-streaming, chunk updates, stop action, chat container и custom element architecture | Особенно полезно для AI chat и embed widget; адаптировать terminology и citation experience к RAG‑Studio | **Chat / widget inspiration** citeturn6search1turn6search9turn6search8 |
| **Carbon conversational search / citations** — [chat.carbondesignsystem.com docs](https://chat.carbondesignsystem.com/tag/latest/docs/) | RAG-specific citation structure и source references | Делать citation объектом first-class data model, а не markdown decoration, чтобы UI мог открывать source inspector | **Chat inspiration** citeturn6search16turn6search21 |
| **OpenAI Company Knowledge** — [openai.com/index/introducing-company-knowledge](https://openai.com/index/introducing-company-knowledge/) | Clear citations к корпоративным источникам | Сильный trust principle: answer должен легко приводить пользователя к evidence. Адаптировать к документам/workspaces RAG‑Studio | **Chat inspiration** citeturn11search13 |
| **Intercom Messenger** — [intercom.com/help/en/articles/6612589-set-up-and-customize-the-messenger](https://www.intercom.com/help/en/articles/6612589-set-up-and-customize-the-messenger) | Управляемое брендирование messenger без полного разрушения component system | Widget должен позволять logo/accent/radius/theme, но сохранять собственную accessible structure | **Widget inspiration** citeturn4search3turn4search11 |
| **Intercom multi-brand Messenger** — [intercom.com/help/en/articles/3946163-style-your-messenger-to-support-multiple-brands](https://www.intercom.com/help/en/articles/3946163-style-your-messenger-to-support-multiple-brands) | Per-brand color/logo/background model | Особенно полезно для multi-tenant deployment: branding принадлежит chatbot/workspace, а не глобальному app theme | **Widget inspiration** citeturn4search19 |
| **Stripe Pricing** — [stripe.com/pricing](https://stripe.com/pricing) | Коммерческая информационная плотность и иерархия тарификации | Изучать, как много pricing detail можно показать без «sales-card circus»; адаптировать структуру, не visual skin | **Landing/pricing inspiration** citeturn4search2 |
| **Stripe Elements** — [stripe.com/payments/elements](https://stripe.com/payments/elements) | Accessible reusable payment/form elements, masking/error/autofill considerations | Полезный принцип для billing forms: polished UI означает прежде всего correct interaction states | **Application inspiration** citeturn4search6 |
| **WorkOS AuthKit branding** — [workos.com/docs/authkit/branding](https://workos.com/docs/authkit/branding) | Restricted but meaningful auth branding: logo, colors, layout, radius, dark mode, legal | Auth RAG‑Studio должен быть брендовым, но гораздо спокойнее landing | **Application/auth inspiration** citeturn12search2turn12search8 |
| **Carbon Data Table** — [carbondesignsystem.com/components/data-table/usage](https://carbondesignsystem.com/components/data-table/usage/) | Table density, states, pagination/search patterns | Использовать настоящие таблицы там, где пользователь сравнивает objects, вместо grid of cards | **Dashboard inspiration** citeturn6search7 |
| **shadcn/ui Command** — [ui.shadcn.com/docs/components/base/command](https://ui.shadcn.com/docs/components/base/command) | Command palette primitive + keyboard shortcut pattern | Хорошая техническая база для `⌘K / Ctrl+K`: search documents, switch workspace, create chatbot, navigation | **Application-shell inspiration** citeturn5search13 |

Из всех этих референсов особенно полезно совместить четыре идеи: **Linear — визуальная тишина**, **Primer/Carbon — системность и data-heavy UI**, **OpenAI/Carbon AI Chat — citations как trust mechanism**, **Intercom — widget как ограниченно брендируемый продукт внутри чужой страницы**. citeturn4search4turn1search14turn11search13turn6search16turn4search3

Важно не собирать Frankenstein UI: Vercel typography + Linear sidebar + Stripe gradients + Intercom widget визуально дадут именно generic SaaS. Референсы должны определять **правила**, а собственная идентичность — появляться из повторяющихся пропорций RAG‑Studio: характерного indigo, спокойных `10–12px` radii, document-first composition, citation treatment, stage indicators и consistent source iconography.

## Финальная рекомендация

Рекомендуемое направление — **Calm Knowledge Instrument**.

У RAG‑Studio должно быть два уровня визуальной энергии:

**Marketing:** немного более editorial, один атмосферный gradient/light field, большие product compositions, restrained reveals.

**Product:** почти никакой атмосферы; основа — typography, information density, semantic surfaces, citations, provenance, state transitions и excellent microinteraction.

Премиальность достигается не количеством эффектов, а тем, что **каждый pixel выглядит намеренным, каждое состояние предусмотрено, а любое действие даёт предсказуемую обратную связь**.

| Использовать часто | Использовать редко | Избегать |
|---|---|---|
| Hairline borders | Static gradient mesh | Animated knowledge networks |
| Layered semantic surfaces | Ambient radial glow | Постоянная aurora |
| Strong typography hierarchy | `1–2%` grain | Heavy glassmorphism |
| Focus/hover/pressed states | Glass на одном floating layer | Glass tables/forms |
| Real ingestion progress | Gradient headline fragment | Purple/cyan glow everywhere |
| Semantic status badges | Static dot/grid background | Neon/chromatic aberration |
| Empty/error/success states | Scroll reveal landing sections | App-level parallax |
| Skeleton for initial loading | Tiny hero parallax — скорее вообще не нужен | Typewriter marketing headline |
| Real AI streaming + Stop | Highlighted edge on special card | Fake AI streaming delay |
| Citations/source inspector | Subtle shadow on normal card | Confetti |
| Command menu/shortcuts | Small branded illustration | Decorative charts |
| Functional microinteractions | Translucent landing nav | Hover-only essential controls |

**Десять implementation priorities:**

1. **Сначала semantic design tokens.** Создать color/surface/text/border/status/elevation/radius/motion tokens и связать их с Tailwind + shadcn CSS variables. shadcn сам рекомендует theming через CSS variables, что хорошо совпадает с этой архитектурой. citeturn5search19
2. **Построить responsive application shell.** Workspace switcher, sidebar, top actions, mobile navigation и `⌘K/Ctrl+K` становятся стабильным каркасом всех admin surfaces.
3. **Сделать ingestion настоящей state machine.** Backend status → frontend semantic stage → per-file progress/error/retry. Никаких fake percentages.
4. **Сделать citations first-class.** Citation имеет ID, document/source title, location/range, snippet, URL/action и availability state. Carbon AI Chat уже демонстрирует RAG citation model такого типа. citeturn6search21
5. **Правильно реализовать streaming.** Immediate user message, retrieval status, real chunks, Stop, partial-error handling, stable scroll.
6. **Спроектировать widget отдельно.** Shadow root, маленький style bundle, CSS-variable API, explicit Radix portal container, responsive full-screen mobile behavior. citeturn3search0turn15search0
7. **Закрыть state matrix компонентов.** Default/hover/focus/active/disabled/loading/error/success/empty/offline/permission-denied до декоративной полировки.
8. **Создать mobile alternatives для data-heavy UI.** Не просто `overflow-x-auto`; определить, какие tables становятся records, sheets или detail pages.
9. **Внедрить единый motion layer + reduced motion.** Короткий token set, никакой случайной Framer-style motion на уровне отдельных разработчиков. citeturn2search21turn0search2
10. **Ввести visual/performance/accessibility release gate.** Проверять focus, contrast, keyboard, `360px`, dark mode, reduced motion, throttled CPU/network и widget isolation. Responsive design и accessibility должны быть системными требованиями, а не отдельным enhancement. citeturn1search5turn0search0

**Anti-generic checklist:**

- В grayscale screenshot всё ещё видна характерная иерархия RAG‑Studio.
- Бренд не зависит от purple glow.
- На рабочем экране нет декоративного эффекта без функции.
- AI обозначается действием и provenance, а не sparkles.
- Citations визуально важнее «магического» AI indicator.
- Реальный product UI является главным marketing visual.
- Dashboard не начинается с четырёх одинаковых KPI cards по привычке.
- Cards используются как смысловые группы, а не как универсальный container.
- App UI заметно спокойнее landing.
- Одна accent family; semantic colors не превращаются в branding palette.
- Multi-tenant context — текущий workspace — всегда ясно виден.
- Ошибка не исчезает в toast, если пользователю надо что-то исправить.
- Mobile имеет собственную information hierarchy, а не просто stacked desktop.
- Widget остаётся узнаваемым RAG‑Studio, но может принять brand клиента.
- Любая animation проходит вопрос: «какую причинно-следственную связь она объясняет?»
- Никакой fake waiting, fake streaming и fake progress.

**Предлагаемый `DESIGN.md` brief:**

```md
# RAG-Studio Design System

## Design direction

RAG-Studio is a Calm Knowledge Instrument.

The product should feel:
- credible;
- calm;
- precise;
- technically sophisticated;
- document- and evidence-oriented;
- premium without decorative excess.

The product must not resemble:
- a crypto dashboard;
- a gaming interface;
- a neon AI demo;
- a generic purple-gradient SaaS template.

Marketing surfaces may be visually expressive.
Application surfaces must remain quiet and information-first.

## Core principles

1. Trust before spectacle.
2. Sources and system state are first-class UI.
3. Structure comes from spacing and hierarchy before borders.
4. Shadows indicate real elevation, not decoration.
5. One brand accent family; semantic colors keep their semantic roles.
6. Motion explains causality.
7. Never fake progress, AI latency, or streaming.
8. Every core workflow works with keyboard and touch.
9. Mobile is designed explicitly from 360px upward.
10. Widget UI remains isolated and reliable on arbitrary host pages.

## Colors

Light:
--bg: #F7F8FA;
--surface: #FFFFFF;
--surface-subtle: #F1F3F5;
--text: #101418;
--text-muted: #5B6672;
--border-subtle: #DDE2E7;
--border-control: #7A8794;
--accent: #4156D9;
--success: #16794A;
--warning: #8A5A00;
--danger: #B42318;
--info: #2459C3;

Dark:
--bg: #0D1014;
--surface: #13181D;
--surface-subtle: #192027;
--text: #F5F7FA;
--text-muted: #A6B0BA;
--border: #2A333C;
--accent: #8EA0FF;

Never communicate status using color alone.

## Typography

Primary UI font:
Inter Variable, system-ui, sans-serif.

Mono:
ui-monospace or project-approved mono font.

App body:
14–16px, 1.45–1.55 line height.

Long-form/document text:
16–18px, 1.5–1.65 line height.

App H1:
28–32px.

Marketing H1:
56–72px desktop;
38–44px mobile.

Use mono only for technical values, identifiers, code, limits, and usage data.

## Spacing

Use a 4px base with an 8px dominant rhythm:

4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96.

Do not introduce arbitrary spacing values without a component-specific reason.

## Radius

Dense control: 6px
Button/input: 8px
Card/popover: 10–12px
Dialog/marketing panel: 14–16px
Pill/badge/avatar: 999px only when semantically appropriate

Avoid universal large-radius cards.

## Elevation

Normal cards:
no shadow.

Floating local controls:
0 1px 2px rgb(16 24 40 / .06)

Menus/popovers:
0 1px 2px rgb(16 24 40 / .05),
0 8px 24px rgb(16 24 40 / .08)

Dialogs/command palette:
0 4px 8px rgb(16 24 40 / .06),
0 20px 48px rgb(16 24 40 / .12)

In dark mode, prefer layer contrast and borders over stronger shadows.

## Borders

Use 1px semantic borders.

Subtle borders organize non-essential regions.
Controls requiring a visible boundary use stronger control-border tokens.

Selected states use:
- border change;
- subtle surface tint;
- optional icon/check;
not color alone.

Focus is independent of normal borders:
2px focus ring + 2px offset.

## Icons

Use Lucide.

16px compact actions
18px default
20px navigation/toolbars
24px marketing and small empty states

Icon-only buttons require accessible names.
Do not use sparkle icons as a generic AI indicator.

## Cards

Cards exist only for meaningful grouping.

Default:
surface background;
1px subtle border;
10–12px radius;
no shadow.

Do not wrap every block in a card.

## Forms

Labels remain visible.
Placeholder is never the label.

Field order:
label
control
helper/error

Desktop controls:
36–40px visual height.

Mobile primary/touch controls:
44px+ effective target.

Use inline errors near the responsible field.

## Tables

Use semantic tables for tabular data.

Desktop rows:
approximately 44–48px by default.

On mobile choose deliberately:
- remove low-priority columns;
- convert rows to structured records;
- open a detail page/sheet.

Do not rely on invisible horizontal scrolling for primary actions.

## Status

Common states:
Draft
Queued
Uploading
Extracting
Indexing
Ready
Paused
Failed
Near limit

Status uses text plus color and, where useful, an icon.

Status badges should be quiet, compact, and low-saturation.

## Charts

Use charts only when shape/trend/comparison matters.

Preferred:
line;
bar;
area.

Avoid decorative charts.

Keep categorical palettes small.
Critical values must also exist as text or accessible tabular data.

## AI chat

Messages use stable readable widths.

AI answers must support:
- real streaming;
- Stop;
- retry;
- partial-response errors;
- copy;
- citations;
- source inspector.

Never simulate character-by-character typing.

Citation data is first-class:
id
source/document id
title
location/range
snippet
URL/action
availability state

Desktop sources may open in a right-side inspector.
Mobile sources open in a bottom sheet/fullscreen view.

Do not force auto-scroll when the user is reading earlier content.

## Document ingestion

Pipeline states are explicit:

Queued
Uploading
Extracting
Preparing
Indexing
Ready
Failed

Show a real percentage only when the backend can calculate it.

Unknown-duration operations use an indeterminate indicator plus a named stage.

Failures remain visible and provide Retry where possible.

No confetti.

## Empty states

An empty state explains:
1. what is empty;
2. why this is expected;
3. the next useful action.

Use small illustrations only when they improve understanding.

## Motion

Tokens:

press: 80ms
fast: 120ms
control: 160ms
overlay: 180–220ms
dialog: 220–260ms
layout: 240–300ms

Avoid routine application animation above 400ms.

Prefer transform and opacity.

Do not animate application content for decoration.

Top-level navigation may use a short fade.
Do not slide the entire application between pages.

## Reduced motion

Respect prefers-reduced-motion.

Disable:
- parallax;
- decorative background movement;
- aurora movement;
- translate/scale reveals;
- animated grids.

Use instant state changes or short opacity transitions instead.

## Visual effects

Use frequently:
- semantic surfaces;
- hairline borders;
- restrained elevation;
- focus/hover/pressed states;
- status transitions;
- skeleton loading;
- real progress;
- real AI streaming.

Use sparingly:
- static radial gradients;
- subtle grain;
- ambient glows;
- gradient headline fragments;
- static dot/grid patterns;
- translucency on isolated floating surfaces;
- marketing scroll reveals.

Avoid:
- animated knowledge-network backgrounds;
- large WebGL/canvas decoration;
- constant aurora;
- pervasive glassmorphism;
- neon glows;
- chromatic effects;
- parallax in application UI;
- fake typewriter effects;
- fake progress;
- fake AI waiting;
- confetti.

## Responsive

Minimum supported viewport:
360px.

Tailwind baseline breakpoints may remain:
sm 640px
md 768px
lg 1024px
xl 1280px
2xl 1536px

Use container-responsive behavior where component width matters more than viewport width.

No page-level horizontal overflow.

Desktop sidebar becomes non-persistent on compact/tablet layouts.

Tables must have explicit mobile alternatives.

Dialogs use viewport-safe margins.
Chat composer respects safe areas and mobile keyboards.

## Accessibility

Target WCAG AA minimum.

Normal text:
4.5:1 contrast minimum.

Large text:
3:1 minimum.

Every core action:
keyboard accessible.

Every interactive element:
visible focus state.

Every icon-only action:
accessible name.

Every status:
not communicated by color alone.

Every dialog:
correct focus lifecycle and accessible title.

Progress:
semantic progress/status representation.

Do not announce every streamed AI token through aria-live.

Primary mobile interaction targets:
44px+ preferred.

## Widget

Use Shadow DOM.

The widget owns its internal styles.
Do not depend on host Tailwind or host typography.

Expose a small theming API:

--rag-accent
--rag-surface
--rag-text
--rag-radius
--rag-font-family

Expose ::part hooks only for intentionally customizable elements.

Radix/shadcn overlays inside the widget must portal into a container
inside the shadow root rather than document.body.

Desktop target window:
approximately 380 × 620px.

Small mobile viewports:
use an inset or fullscreen 100dvh layout.

Keep the widget bundle and effects lightweight.
Do not use ambient glows or backdrop blur by default.

## Definition of premium

Premium does not mean more effects.

For RAG-Studio, premium means:
- precise hierarchy;
- excellent typography;
- predictable states;
- evidence-first AI answers;
- polished keyboard interaction;
- strong mobile behavior;
- fast perceived response;
- trustworthy loading and error handling;
- consistent multi-tenant context;
- zero unnecessary visual noise.
```

Такой brief также хорошо совпадает с техническими преимуществами выбранного стека: shadcn даёт кодируемые и themeable component primitives вместо жёстко закрытой visual library; Radix предоставляет accessibility/focus/keyboard foundation; Tailwind позволяет централизовать responsive, motion и CSS-variable tokens. citeturn5search17turn5search19turn5search16turn5search20turn0search7

Главное отличие RAG‑Studio от generic AI SaaS должно быть не в более эффектном glow. Оно должно быть заметно в том, **как продукт визуализирует происхождение знания, состояние ingestion, границы workspace, уверенность в результате и возможность проверить AI-ответ**. Для корпоративного knowledge product именно эти элементы превращают «красивый интерфейс» в интерфейс, которому можно доверять. Подход с ясными citations уже используется в современных company-knowledge AI experiences, а зрелые enterprise design systems системно ставят semantic hierarchy, state, accessibility и predictable interaction выше декоративной сложности. citeturn11search13turn6search16turn1search13turn2search21
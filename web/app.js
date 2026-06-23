/**
 * Driver's Manual Updates by Year — frontend logic
 *
 * Data flow:
 *  1. Load data/manifest.json → populate year dropdown + pre-fetch accordion data
 *  2. User selects a year → fetch data/changes_{year}_to_{latest}.json → render
 */

const dataCache = {};

// ── Internationalization (EN / ES) ─────────────────────────────────────────────
//
// The English build is the default and unchanged. Selecting ES translates every
// static UI string and switches the data source to the Spanish dataset built from
// the two Spanish manuals (see scripts/build_spanish.py). The dynamic content
// (overview, titles, descriptions, quotes, chapter names) is already Spanish in
// that dataset, so only the chrome below needs translating.

const STRINGS = {
  en: {
    title: "Driver's Manual Updates by Year",
    intro: "Use this tool to see what has changed in the Massachusetts Driver's Manual since you got your driver's license. Click on a result to read the direct quote from the 2026 RMV Driver's Manual and click View All to expand subsections. Right now, only some years are included, so you will see the one closest to the year you enter.",
    disclaimer: "This tool is not intended to be exhaustive or authoritative: it is an informational tool that is meant to improve ease of access to the newest material included in the most recent Massachusetts Driver's Manual.",
    yearLabel: "Enter the year you got your driver's license:",
    yearPlaceholder: "e.g. 2015",
    yearSubmitAria: "Submit year",
    accordionLabel: (y) => `${y} Updates`,
    accordionLoading: (y) => `Loading ${y} updates…`,
    accordionError: (y) => `Could not load ${y} update data.`,
    changesHeading: (y) => `Changes Since ${y}`,
    searchPlaceholder: "Search the updates…",
    searchAria: "Search the updates",
    share: "Share",
    sharePdf: "Print / Save as PDF",
    shareEmail: "Email the results",
    shareCopy: "Copy the link",
    shareCopied: "Copied!",
    shareCopyFailed: "Copy failed",
    sharePreparing: "Preparing…",
    filterNew: "New",
    filterUpdated: "Updated",
    filterExpanded: "Expanded",
    filterRemoved: "Removed",
    viewAll: "View All",
    hide: "Hide",
    jumpTo: "Jump to a section:",
    resultsEmpty: "No matching updates. Try clearing the search or filters.",
    noChangesEditions: "No significant changes identified between these editions.",
    noChangesPeriod: "No significant changes identified for this period.",
    statusYearDataError: "Could not load year data. Please refresh the page.",
    statusInvalid: "Invalid Input",
    statusLoading: "Loading…",
    statusOnlyBackTo: (y) => `We only have manual data going back to ${y}.`,
    statusUpdateError: "Could not load update data. Please try again.",
    scrollTopAria: "Scroll to top",
    citationTitle: (y, p) => `Open the ${y} Massachusetts Driver's Manual at page ${p}`,
    emailSubjectPrefix: "MA Driver's Manual — ",
    emailDefaultHeading: "Driver's Manual Updates",
    emailViewFull: "View the full results here:",
    // Change-type badge text — English keeps the raw lowercase value (unchanged).
    badge: { new: "new", updated: "updated", expanded: "expanded", removed: "removed" },
  },
  es: {
    title: "Actualizaciones del Manual del Conductor por Año",
    intro: "Use esta herramienta para ver qué ha cambiado en el Manual del Conductor de Massachusetts desde que obtuvo su licencia de conducir. Haga clic en un resultado para leer la cita directa del Manual del Conductor del RMV de 2023 y haga clic en Ver todo para expandir las subsecciones. Por ahora, solo se incluyen algunos años, por lo que verá el más cercano al año que ingrese.",
    disclaimer: "Esta herramienta no pretende ser exhaustiva ni autorizada: es una herramienta informativa destinada a facilitar el acceso al material más reciente incluido en el Manual del Conductor de Massachusetts más actual.",
    yearLabel: "Ingrese el año en que obtuvo su licencia de conducir:",
    yearPlaceholder: "p. ej. 2015",
    yearSubmitAria: "Enviar año",
    accordionLabel: (y) => `Actualizaciones de ${y}`,
    accordionLoading: (y) => `Cargando actualizaciones de ${y}…`,
    accordionError: (y) => `No se pudieron cargar los datos de actualización de ${y}.`,
    changesHeading: (y) => `Cambios Desde ${y}`,
    searchPlaceholder: "Buscar en las actualizaciones…",
    searchAria: "Buscar en las actualizaciones",
    share: "Compartir",
    sharePdf: "Imprimir / Guardar como PDF",
    shareEmail: "Enviar los resultados por correo",
    shareCopy: "Copiar el enlace",
    shareCopied: "¡Copiado!",
    shareCopyFailed: "Error al copiar",
    sharePreparing: "Preparando…",
    filterNew: "Nuevo",
    filterUpdated: "Actualizado",
    filterExpanded: "Ampliado",
    filterRemoved: "Eliminado",
    viewAll: "Ver todo",
    hide: "Ocultar",
    jumpTo: "Saltar a una sección:",
    resultsEmpty: "No hay actualizaciones coincidentes. Pruebe a borrar la búsqueda o los filtros.",
    noChangesEditions: "No se identificaron cambios significativos entre estas ediciones.",
    noChangesPeriod: "No se identificaron cambios significativos para este período.",
    statusYearDataError: "No se pudieron cargar los datos de los años. Actualice la página.",
    statusInvalid: "Entrada no válida",
    statusLoading: "Cargando…",
    statusOnlyBackTo: (y) => `Solo tenemos datos del manual desde ${y}.`,
    statusUpdateError: "No se pudieron cargar los datos de actualización. Inténtelo de nuevo.",
    scrollTopAria: "Volver arriba",
    citationTitle: (y, p) => `Abrir el Manual del Conductor de Massachusetts de ${y} en la página ${p}`,
    emailSubjectPrefix: "Manual del Conductor de MA — ",
    emailDefaultHeading: "Actualizaciones del Manual del Conductor",
    emailViewFull: "Vea los resultados completos aquí:",
    badge: { new: "Nuevo", updated: "Actualizado", expanded: "Ampliado", removed: "Eliminado" },
  },
};

// Per-language data sources. EN reads the original files; ES reads the *_spanish
// variants and deep-links citations into the Spanish PDFs.
const LANG_CONFIG = {
  en: {
    manifest: 'data/manifest.json',
    subtopics: 'data/subtopics.json',
    changesSuffix: '',
    manualPath: (y) => `manuals/Drivers_Manual_${y}.pdf`,
    // Chapter pinned to the top of the results, ahead of natural chapter order.
    priorityChapter: 'Rules of the Road',
  },
  es: {
    manifest: 'data/manifest_spanish.json',
    subtopics: 'data/subtopics_spanish.json',
    changesSuffix: '_spanish',
    manualPath: (y) => `manuals_spanish/Drivers_Manual_Spanish_${y}.pdf`,
    priorityChapter: 'Reglas de la carretera',
  },
};

// Active language. Resolved at startup from ?lang= / localStorage (default 'en').
let lang = 'en';

// Translate a key for the active language; call the value if it's a formatter.
function t(key, ...args) {
  const v = STRINGS[lang][key];
  return typeof v === 'function' ? v(...args) : v;
}

function cfg() {
  return LANG_CONFIG[lang];
}

// Localized change-type badge text (falls back to the raw value if unmapped).
function badgeLabel(type) {
  return (STRINGS[lang].badge && STRINGS[lang].badge[type]) || type;
}

// Manifest-derived comparison years, kept at module scope so the year handler and
// the language toggle can both read/refresh them.
let FROM_YEARS = [];
let LATEST = null;

// Editable outline of subtopic headings (web/data/subtopics.json), loaded once at
// startup. Each entry: { chapter_num, page, title }. Results are bucketed under the
// nearest preceding heading by citation page. Empty → app degrades to chapter-only.
let SUBTOPICS = [];

// The year the user entered that produced the currently shown results — backs the
// shareable URL, the email body, and the PDF filename.
let currentYear = null;

// True while a search query or change-type filter is active. When set, the
// per-subtopic "first 3 results" cap is suspended so matches aren't hidden.
let filterActive = false;

// ── Manifest / startup ────────────────────────────────────────────────────────

async function loadManifest() {
  const resp = await fetch(cfg().manifest);
  if (!resp.ok) throw new Error(`${cfg().manifest} fetch failed: ${resp.status}`);
  return resp.json();
}

// Subtopic outline is optional — if it can't be loaded, results still render
// grouped by chapter (every result falls into the "General" bucket).
async function loadSubtopics() {
  try {
    const resp = await fetch(cfg().subtopics);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    SUBTOPICS = await resp.json();
  } catch {
    SUBTOPICS = [];
  }
}

async function init() {
  // Resolve initial language: ?lang= wins, else stored preference, else English.
  const params = new URLSearchParams(window.location.search);
  const urlLang = params.get('lang');
  let storedLang = null;
  try { storedLang = localStorage.getItem('rmv_lang'); } catch { /* ignore */ }
  if (urlLang === 'es' || urlLang === 'en') lang = urlLang;
  else if (storedLang === 'es' || storedLang === 'en') lang = storedLang;
  else lang = 'en';

  initLangToggle();

  const input = document.getElementById('year-input');

  // Bind the year handlers once — they read FROM_YEARS / LATEST from module scope,
  // which loadLanguageData() refreshes whenever the language changes.
  const handler = () => handleYearInput(input.value);
  input.addEventListener('change', handler);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handler();
    }
  });
  const submitBtn = document.getElementById('year-submit-btn');
  if (submitBtn) submitBtn.addEventListener('click', handler);

  applyStaticText();
  await loadLanguageData();

  // Reopen a shared view from the URL (?year=…).
  const yearParam = params.get('year');
  if (yearParam) {
    input.value = yearParam;
    handleYearInput(yearParam);
  }
}

// Load (or reload) all data for the active language and refresh the accordion.
// Sets the module-level FROM_YEARS / LATEST the year handler depends on.
async function loadLanguageData() {
  const input = document.getElementById('year-input');
  const accordionLabel = document.getElementById('accordion-label');

  let manifest;
  try {
    manifest = await loadManifest();
  } catch (err) {
    showYearStatus(t('statusYearDataError'), 'error');
    input.disabled = true;
    return;
  }
  input.disabled = false;

  // Subtopic outline backs the nested TOC and the per-subtopic grouping — load it
  // before any rendering so both the accordion and year views can use it.
  await loadSubtopics();

  const { manual_years: years, latest_year: latest } = manifest;
  LATEST = latest;
  // Editions the user can compare against — exclude the latest (that's what we
  // compare *to*). Sorted ascending so we can pick the most recent at-or-before.
  FROM_YEARS = years.filter(year => year !== latest).sort((a, b) => a - b);

  accordionLabel.textContent = t('accordionLabel', latest);

  // Pre-fetch accordion data (second-latest → latest)
  if (FROM_YEARS.length > 0) {
    const secondLatest = FROM_YEARS[FROM_YEARS.length - 1];
    loadChanges(secondLatest, latest).then(data => {
      if (data) renderAccordion(data);
    }).catch(() => {
      document.getElementById('accordion-content').innerHTML =
        `<p class="error-msg">${t('accordionError', latest)}</p>`;
    });
  }
}

// ── Language toggle ─────────────────────────────────────────────────────────────

function initLangToggle() {
  const enBtn = document.getElementById('lang-en');
  const esBtn = document.getElementById('lang-es');
  if (!enBtn || !esBtn) return;
  enBtn.addEventListener('click', () => setLanguage('en'));
  esBtn.addEventListener('click', () => setLanguage('es'));
  reflectLangToggle();
}

function reflectLangToggle() {
  const enBtn = document.getElementById('lang-en');
  const esBtn = document.getElementById('lang-es');
  if (!enBtn || !esBtn) return;
  enBtn.classList.toggle('is-active', lang === 'en');
  esBtn.classList.toggle('is-active', lang === 'es');
  enBtn.setAttribute('aria-pressed', String(lang === 'en'));
  esBtn.setAttribute('aria-pressed', String(lang === 'es'));
}

async function setLanguage(next) {
  if (next === lang || (next !== 'en' && next !== 'es')) return;
  lang = next;
  try { localStorage.setItem('rmv_lang', lang); } catch { /* ignore */ }

  reflectLangToggle();
  applyStaticText();
  showYearStatus('');               // drop any stale "before oldest" warning
  syncUrl();

  await loadLanguageData();          // refresh FROM_YEARS / LATEST + accordion

  // Re-render the currently entered year against the new dataset, if any.
  const input = document.getElementById('year-input');
  if (currentYear != null && input.value.trim()) {
    handleYearInput(input.value);
  } else {
    document.getElementById('changes-section').hidden = true;
  }
}

// Translate every static (non-data) string for the active language.
function applyStaticText() {
  document.documentElement.lang = lang;
  document.title = t('title');

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('app-title', t('title'));
  set('app-intro', t('intro'));
  set('app-disclaimer', t('disclaimer'));
  set('year-label', t('yearLabel'));

  const input = document.getElementById('year-input');
  if (input) input.placeholder = t('yearPlaceholder');
  const submitBtn = document.getElementById('year-submit-btn');
  if (submitBtn) submitBtn.setAttribute('aria-label', t('yearSubmitAria'));

  if (LATEST != null) set('accordion-label', t('accordionLabel', LATEST));

  const search = document.getElementById('results-search');
  if (search) {
    search.placeholder = t('searchPlaceholder');
    search.setAttribute('aria-label', t('searchAria'));
  }

  const shareSpan = document.querySelector('#share-btn span');
  if (shareSpan) shareSpan.textContent = t('share');
  const shareMap = { pdf: 'sharePdf', email: 'shareEmail', copy: 'shareCopy' };
  document.querySelectorAll('.share-option').forEach(opt => {
    const key = shareMap[opt.dataset.action];
    if (key) opt.textContent = t(key);
  });

  const filterMap = { new: 'filterNew', updated: 'filterUpdated', expanded: 'filterExpanded', removed: 'filterRemoved' };
  document.querySelectorAll('#results-filters .filter-chip').forEach(chip => {
    const cb = chip.querySelector('input');
    const span = chip.querySelector('span');
    if (cb && span && filterMap[cb.value]) span.textContent = t(filterMap[cb.value]);
  });

  const empty = document.getElementById('results-empty');
  if (empty) empty.textContent = t('resultsEmpty');
  const scrollTop = document.getElementById('scroll-top');
  if (scrollTop) scrollTop.setAttribute('aria-label', t('scrollTopAria'));
}

// Reflect the active language + current year in the URL so the view is shareable.
function syncUrl() {
  const url = new URL(window.location.href);
  const params = new URLSearchParams();
  if (lang !== 'en') params.set('lang', lang);
  if (currentYear != null) params.set('year', currentYear);
  const qs = params.toString();
  url.search = qs ? `?${qs}` : '';
  url.hash = '';
  history.replaceState(null, '', url.toString());
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadChanges(fromYear, toYear) {
  // Cache is namespaced by language so EN and ES datasets never collide.
  const key = `${lang}_${fromYear}_${toYear}`;
  if (dataCache[key]) return dataCache[key];

  const resp = await fetch(`data/changes_${fromYear}_to_${toYear}${cfg().changesSuffix}.json`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  dataCache[key] = data;
  return data;
}

// ── Year input ──────────────────────────────────────────────────────────────

async function handleYearInput(rawValue) {
  const changesSection = document.getElementById('changes-section');
  const value = rawValue.trim();

  // Anything that isn't a four-digit year is rejected outright.
  if (!/^\d{4}$/.test(value)) {
    changesSection.hidden = true;
    showYearStatus(t('statusInvalid'), 'error');
    return;
  }

  const enteredYear = parseInt(value, 10);

  // Most recent edition at or before the entered year (e.g. 2009 → 2007).
  let fromYear = null;
  for (const y of FROM_YEARS) {
    if (y <= enteredYear) fromYear = y;
  }

  // Years before our oldest edition: warn, but still show the oldest edition's
  // updates as the closest available match.
  const beforeOldest = fromYear === null;
  if (beforeOldest) fromYear = FROM_YEARS[0];

  showYearStatus(beforeOldest
    ? t('statusOnlyBackTo', FROM_YEARS[0])
    : t('statusLoading'),
    beforeOldest ? 'error' : '');

  try {
    const data = await loadChanges(fromYear, LATEST);
    renderChanges(data, fromYear, LATEST);
    // Preserve the warning when we fell back to the oldest edition.
    if (!beforeOldest) showYearStatus('');
    // Reflect the view in the URL so it can be shared / reopened.
    currentYear = enteredYear;
    syncUrl();
  } catch (err) {
    showYearStatus(t('statusUpdateError'), 'error');
    changesSection.hidden = true;
  }
}

function showYearStatus(msg, type = '') {
  const el = document.getElementById('year-status');
  el.textContent = msg;
  el.className = type === 'error' ? 'error' : '';
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderChanges(data, fromYear, toYear) {
  const changesSection = document.getElementById('changes-section');
  const heading = document.getElementById('changes-heading');
  const overviewBlock = document.getElementById('overview-block');
  const sectionsList = document.getElementById('sections-list');
  const idPrefix = `changes-${fromYear}`;

  heading.textContent = t('changesHeading', fromYear);
  overviewBlock.innerHTML = '';
  sectionsList.innerHTML = '';
  resetResultsControls();

  // Summary paragraph (paraphrased, no direct quotes)
  if (data.overview) {
    overviewBlock.appendChild(buildSummaryParagraph(data.overview));
  }

  if (!data.sections || data.sections.length === 0) {
    sectionsList.innerHTML = `<p class="info-msg">${t('noChangesEditions')}</p>`;
    changesSection.hidden = false;
    return;
  }

  const groups = groupByChapter(data.sections);

  // Table of contents inside the blue box (chapter pills)
  overviewBlock.appendChild(buildTableOfContents(groups, idPrefix));

  // Grouped change cards with anchored chapter headings
  groups.forEach(group => {
    sectionsList.appendChild(buildChapterGroup(group, idPrefix));
  });

  changesSection.hidden = false;
}

function renderAccordion(data) {
  const content = document.getElementById('accordion-content');
  content.innerHTML = '';

  if (!data.sections || data.sections.length === 0) {
    content.innerHTML = `<p class="info-msg">${t('noChangesPeriod')}</p>`;
    return;
  }

  groupByChapter(data.sections).forEach(group => {
    content.appendChild(buildChapterGroup(group, 'accordion'));
  });
}

// ── Chapter grouping + table of contents ───────────────────────────────────────

function groupByChapter(sections) {
  const groups = new Map();
  sections.forEach(sec => {
    const chapter = sec.chapter || 'Other Updates';
    const num = (sec.chapter_num != null) ? sec.chapter_num : 98;
    if (!groups.has(chapter)) {
      groups.set(chapter, { chapter, chapter_num: num, items: [] });
    }
    groups.get(chapter).items.push(sec);
  });
  // The priority chapter (English "Rules of the Road" / Spanish "Reglas de la
  // carretera") is highlighted by always sorting first; the rest keep their
  // natural chapter order.
  const priority = cfg().priorityChapter;
  const rank = g => (g.chapter === priority ? -Infinity : g.chapter_num);
  return [...groups.values()].sort((a, b) => rank(a) - rank(b));
}

function groupAnchorId(prefix, chapter) {
  const slug = chapter.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${prefix}-group-${slug}`;
}

function subtopicAnchorId(prefix, chapter, subtopicTitle) {
  const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${prefix}-sub-${slug(chapter)}-${slug(subtopicTitle)}`;
}

// Lowest citation page for a change result, or null when it has no page citation.
function resultPage(sec) {
  const pages = (sec.citations || [])
    .map(c => c && c.page)
    .filter(p => typeof p === 'number');
  return pages.length ? Math.min(...pages) : null;
}

/**
 * Partition a chapter's results into ordered subtopic buckets. Each result is
 * placed under the subtopic whose page is the greatest at-or-before its citation
 * page. Results with no citation, or that fall before the chapter's first heading,
 * collect in a leading "General" bucket (rendered without a subheading). Subtopics
 * with no results are dropped. Returns [{ title, items }] in document order.
 *
 * Pure (config passed in) so it can be unit-tested in Node.
 */
function bucketBySubtopic(items, chapterNum, subtopics) {
  const headings = (subtopics || [])
    .filter(s => s.chapter_num === chapterNum)
    .sort((a, b) => a.page - b.page);

  const general = [];
  const byTitle = new Map();   // title → items[], insertion-ordered by page

  items.forEach(sec => {
    const page = resultPage(sec);
    let chosen = null;
    if (page != null) {
      for (const h of headings) {
        if (h.page <= page) chosen = h; else break;
      }
    }
    if (!chosen) {
      general.push(sec);
      return;
    }
    if (!byTitle.has(chosen.title)) byTitle.set(chosen.title, []);
    byTitle.get(chosen.title).push(sec);
  });

  const buckets = [];
  if (general.length) buckets.push({ title: 'General', items: general });
  headings.forEach(h => {
    const list = byTitle.get(h.title);
    if (list && list.length) buckets.push({ title: h.title, items: list });
  });
  return buckets;
}

function buildSummaryParagraph(text) {
  const p = document.createElement('p');
  p.className = 'overview-summary';
  p.textContent = text;
  return p;
}

/**
 * Scroll a chapter heading into view, reliably.
 *
 * Inline images are lazy-loaded and have no reserved height, so an unloaded
 * figure collapses to ~0px. If we scroll before the images ABOVE the target
 * have loaded, they expand afterward and push the heading away from where we
 * landed — the drift grows with the number of images above it, which is why
 * long pages (2007/2017) used to land in the wrong place. Fix: force every
 * image above the target to its final height first, then scroll once.
 */
function scrollToHeading(targetId) {
  const target = document.getElementById(targetId);
  if (!target) return;

  const go = () => {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    target.classList.add('group-flash');
    setTimeout(() => target.classList.remove('group-flash'), 1400);
  };

  // Images that precede the target in the document and are currently visible
  // can still change the target's position once they finish loading.
  const pending = [];
  document.querySelectorAll('img').forEach(img => {
    const precedesTarget =
      !!(target.compareDocumentPosition(img) & Node.DOCUMENT_POSITION_PRECEDING);
    const visible = img.offsetParent !== null;
    if (!precedesTarget || !visible || img.complete) return;
    img.loading = 'eager';
    pending.push(new Promise(resolve => {
      img.addEventListener('load', resolve, { once: true });
      img.addEventListener('error', resolve, { once: true });
    }));
  });

  if (pending.length === 0) {
    go();
    return;
  }

  // Scroll once the above-images settle, but never block on a slow/missing one.
  Promise.race([
    Promise.all(pending),
    new Promise(resolve => setTimeout(resolve, 1500)),
  ]).then(go);
}

// A TOC jump link that autoscrolls (and flashes) its target heading.
function buildTocLink(targetId, text, className) {
  const a = document.createElement('a');
  a.className = className;
  a.href = `#${targetId}`;
  a.textContent = text;
  a.addEventListener('click', (e) => {
    e.preventDefault();
    scrollToHeading(targetId);
  });
  return a;
}

/**
 * Table of contents inside the blue box: one pill button per chapter (top-level
 * taxonomy only). Each pill autoscrolls to its anchored chapter heading. Entries
 * hide via applyFilters when all of a chapter's results are filtered out.
 */
function buildTableOfContents(groups, idPrefix) {
  const nav = document.createElement('nav');
  nav.className = 'toc';
  nav.setAttribute('aria-label', 'Topic areas');

  const label = document.createElement('p');
  label.className = 'toc-label';
  label.textContent = t('jumpTo');
  nav.appendChild(label);

  const ul = document.createElement('ul');
  ul.className = 'toc-list';

  groups.forEach(group => {
    const targetId = groupAnchorId(idPrefix, group.chapter);
    const li = document.createElement('li');
    li.appendChild(buildTocLink(targetId, group.chapter, 'toc-pill'));
    ul.appendChild(li);
  });

  nav.appendChild(ul);
  return nav;
}

// Number of result pills shown per chapter before "View All" is offered.
const SECTION_VISIBLE_LIMIT = 3;

function buildChapterGroup(group, idPrefix) {
  const wrap = document.createElement('section');
  wrap.className = 'change-group';

  const heading = document.createElement('h3');
  heading.className = 'group-heading';
  heading.id = groupAnchorId(idPrefix, group.chapter);
  heading.textContent = group.chapter;
  wrap.appendChild(heading);

  // All of a chapter's results render flat (no subtopic headings). The section
  // wrapper backs the "first 3 + View All" collapse, now applied per chapter.
  const section = document.createElement('div');
  section.className = 'results-section';

  group.items.forEach(sec => section.appendChild(buildSectionCard(sec)));

  // "View All" / "Hide" toggle — only meaningful past the visible limit.
  if (group.items.length > SECTION_VISIBLE_LIMIT) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'view-toggle';

    const label = document.createElement('span');
    label.className = 'vt-label';
    btn.appendChild(label);

    const caret = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    caret.setAttribute('class', 'vt-caret');
    caret.setAttribute('viewBox', '0 0 24 24');
    caret.setAttribute('aria-hidden', 'true');
    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    poly.setAttribute('points', '6 9 12 15 18 9');
    caret.appendChild(poly);
    btn.appendChild(caret);

    btn.addEventListener('click', () => {
      section.dataset.expanded = section.dataset.expanded === 'true' ? 'false' : 'true';
      applySectionCollapse(section);
    });
    section.appendChild(btn);
  }

  wrap.appendChild(section);
  applySectionCollapse(section);

  return wrap;
}

/**
 * Enforce the per-chapter "first 3 results" rule on one section. The 4th visible
 * pill gets a gradient teaser (.result-teaser); the rest hide (.result-overflow);
 * a "View All" button reveals everything ("Hide" collapses back). When a
 * search/filter is active the cap is suspended so matches aren't trapped behind
 * the teaser. Re-run on render and whenever filters change.
 */
function applySectionCollapse(section) {
  const cards = [...section.querySelectorAll('.section-card')]
    .filter(c => !c.classList.contains('is-hidden'));
  cards.forEach(c => c.classList.remove('result-teaser', 'result-overflow'));

  const btn = section.querySelector('.view-toggle');
  const expanded = section.dataset.expanded === 'true';
  const capped = !filterActive && !expanded && cards.length > SECTION_VISIBLE_LIMIT;

  if (capped) {
    cards.forEach((c, i) => {
      if (i === SECTION_VISIBLE_LIMIT) c.classList.add('result-teaser');
      else if (i > SECTION_VISIBLE_LIMIT) c.classList.add('result-overflow');
    });
  }

  if (btn) {
    // Hide the button while filtering (all matches already shown) or when there's
    // nothing past the limit; otherwise label it for the current state.
    btn.hidden = filterActive || cards.length <= SECTION_VISIBLE_LIMIT;
    const label = btn.querySelector('.vt-label');
    if (label) label.textContent = expanded ? t('hide') : t('viewAll');
  }
}

function buildCitationLink({ year, page }) {
  const a = document.createElement('a');
  a.className = 'citation-link';
  a.href = `${cfg().manualPath(year)}#page=${page}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = `(p. ${page})`;
  a.title = t('citationTitle', year, page);
  return a;
}

// Unique id source for card-toggle ↔ card-body wiring (aria-controls).
let cardSeq = 0;

/**
 * A single change result rendered as a collapsible pill. Collapsed by default it
 * shows only the title, change-type badge, and subtitle (the description). Clicking
 * the pill reveals the body: the direct quote(s) with PDF citations and any images.
 * The body stays in the DOM while collapsed (hidden via CSS) so search and
 * Print/Save-as-PDF still see its content.
 */
function buildSectionCard(sec) {
  const card = document.createElement('div');
  card.className = 'section-card';

  // Filterable metadata (used by applyFilters): change type + searchable text.
  card.dataset.type = sec.change_type || '';
  card.dataset.search = [sec.title, sec.description, ...(sec.bullets || [])]
    .filter(Boolean).join(' ').toLowerCase();

  const bodyId = `card-body-${++cardSeq}`;

  // Clickable header (collapsed view): title + badge + subtitle + caret.
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'card-toggle';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.setAttribute('aria-controls', bodyId);

  const main = document.createElement('span');
  main.className = 'card-toggle-main';

  const headLine = document.createElement('span');
  headLine.className = 'card-toggle-head';

  // A span (not a heading) — the title lives inside a <button>, whose content
  // model only allows phrasing content.
  const title = document.createElement('span');
  title.className = 'card-title';
  title.textContent = sec.title || 'Update';
  headLine.appendChild(title);

  if (sec.change_type) {
    const badge = document.createElement('span');
    badge.className = `badge badge-${sec.change_type}`;
    badge.textContent = badgeLabel(sec.change_type);
    headLine.appendChild(badge);
  }
  main.appendChild(headLine);

  if (sec.description) {
    const subtitle = document.createElement('span');
    subtitle.className = 'card-subtitle';
    subtitle.textContent = sec.description;
    main.appendChild(subtitle);
  }
  toggle.appendChild(main);

  // Caret mirrors the accordion chevron; rotates via CSS on aria-expanded.
  const caret = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  caret.setAttribute('class', 'card-caret');
  caret.setAttribute('viewBox', '0 0 24 24');
  caret.setAttribute('aria-hidden', 'true');
  const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  poly.setAttribute('points', '6 9 12 15 18 9');
  caret.appendChild(poly);
  toggle.appendChild(caret);

  card.appendChild(toggle);

  // Expandable body: direct quotes + images.
  const body = document.createElement('div');
  body.className = 'card-body';
  body.id = bodyId;

  // Bullets — each is a direct quote; append a page-level PDF citation when one
  // was matched during the build (see scripts/lib/citations.py).
  if (sec.bullets && sec.bullets.length > 0) {
    const ul = document.createElement('ul');
    ul.className = 'section-bullets';
    sec.bullets.forEach((bullet, i) => {
      const li = document.createElement('li');
      li.textContent = bullet;
      const citation = sec.citations && sec.citations[i];
      if (citation) {
        li.appendChild(document.createTextNode(' '));
        li.appendChild(buildCitationLink(citation));
      }
      ul.appendChild(li);
    });
    body.appendChild(ul);
  }

  // Images — laid out in a wrapping flex row so multiple fit per line
  if (sec.images && sec.images.length > 0) {
    const gallery = document.createElement('div');
    gallery.className = 'section-figures';

    sec.images.forEach(img => {
      const figure = document.createElement('figure');
      figure.className = 'section-figure';

      const image = document.createElement('img');
      image.src = img.src;
      image.alt = img.alt || sec.title || '';
      image.loading = 'lazy';
      figure.appendChild(image);

      if (img.caption) {
        const caption = document.createElement('figcaption');
        caption.textContent = img.caption;
        figure.appendChild(caption);
      }

      gallery.appendChild(figure);
    });

    body.appendChild(gallery);
  }

  card.appendChild(body);

  toggle.addEventListener('click', () => {
    const open = card.classList.toggle('is-open');
    toggle.setAttribute('aria-expanded', String(open));
  });

  return card;
}

// ── Accordion toggle ──────────────────────────────────────────────────────────

function initAccordion() {
  const toggle = document.getElementById('accordion-toggle');
  const body = document.getElementById('accordion-body');

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    const nowExpanded = !expanded;

    toggle.setAttribute('aria-expanded', String(nowExpanded));

    if (nowExpanded) {
      body.hidden = false;
      // Allow display before animating height
      requestAnimationFrame(() => {
        body.style.maxHeight = body.scrollHeight + 'px';
      });
    } else {
      body.style.maxHeight = '0';
      body.addEventListener('transitionend', () => {
        if (toggle.getAttribute('aria-expanded') === 'false') {
          body.hidden = true;
          body.style.maxHeight = '';
        }
      }, { once: true });
    }
  });
}

// ── Search + filter controls ────────────────────────────────────────────────

function initResultsControls() {
  const search = document.getElementById('results-search');
  if (search) search.addEventListener('input', applyFilters);
  document.querySelectorAll('#results-filters input').forEach(cb =>
    cb.addEventListener('change', applyFilters));
  initShareMenu();
}

function resetResultsControls() {
  const search = document.getElementById('results-search');
  if (search) search.value = '';
  document.querySelectorAll('#results-filters input:checked').forEach(cb => (cb.checked = false));
  filterActive = false;
  const empty = document.getElementById('results-empty');
  if (empty) empty.hidden = true;
  closeShareMenu();
}

/**
 * Live ctrl+F-style filtering of the rendered results. Combines a text search
 * (substring over each card's title/description/bullets) with the change-type
 * checkboxes (OR among checked types; no checkboxes = show all). Subtopic
 * subsections, chapter groups, and their table-of-contents entries hide when none
 * of their cards match. While any filter is active the per-subtopic "first 3" cap
 * is suspended so every match shows.
 */
function applyFilters() {
  const sectionsList = document.getElementById('sections-list');
  if (!sectionsList) return;

  const query = (document.getElementById('results-search').value || '').trim().toLowerCase();
  const activeTypes = [...document.querySelectorAll('#results-filters input:checked')]
    .map(cb => cb.value);
  filterActive = query !== '' || activeTypes.length > 0;

  let anyVisible = false;
  sectionsList.querySelectorAll('.section-card').forEach(card => {
    const typeOk = activeTypes.length === 0 || activeTypes.includes(card.dataset.type);
    const textOk = !query || (card.dataset.search || '').includes(query);
    const visible = typeOk && textOk;
    card.classList.toggle('is-hidden', !visible);
    if (visible) anyVisible = true;
  });

  const toc = document.getElementById('overview-block');
  const tocLinkFor = id => (toc && id) ? toc.querySelector(`.toc a[href="#${id}"]`) : null;

  // Re-apply the (possibly suspended) per-chapter cap to each results section.
  sectionsList.querySelectorAll('.results-section').forEach(section => {
    if (section.querySelector('.section-card:not(.is-hidden)')) applySectionCollapse(section);
  });

  sectionsList.querySelectorAll('.change-group').forEach(group => {
    const groupVisible = group.querySelector('.section-card:not(.is-hidden)') !== null;
    group.classList.toggle('is-hidden', !groupVisible);
    const heading = group.querySelector('.group-heading');
    const link = heading && tocLinkFor(heading.id);
    if (link) link.closest('li').classList.toggle('is-hidden', !groupVisible);
  });

  const empty = document.getElementById('results-empty');
  if (empty) empty.hidden = anyVisible;
}

// ── Share menu ──────────────────────────────────────────────────────────────

function initShareMenu() {
  const btn = document.getElementById('share-btn');
  const menu = document.getElementById('share-menu');
  if (!btn || !menu) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.hidden ? openShareMenu() : closeShareMenu();
  });
  menu.querySelectorAll('.share-option').forEach(opt =>
    opt.addEventListener('click', () => handleShareAction(opt)));

  document.addEventListener('click', (e) => {
    if (!menu.hidden && !menu.contains(e.target) && e.target !== btn) closeShareMenu();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeShareMenu();
  });
}

function openShareMenu() {
  document.getElementById('share-menu').hidden = false;
  document.getElementById('share-btn').setAttribute('aria-expanded', 'true');
}

function closeShareMenu() {
  const menu = document.getElementById('share-menu');
  const btn = document.getElementById('share-btn');
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

async function handleShareAction(opt) {
  switch (opt.dataset.action) {
    case 'copy':
      try {
        await navigator.clipboard.writeText(buildShareUrl());
        flashOption(opt, t('shareCopied'));
      } catch {
        flashOption(opt, t('shareCopyFailed'));
      }
      break;
    case 'email':
      emailResults();
      closeShareMenu();
      break;
    case 'pdf':
      printResults(opt);
      break;
  }
}

function flashOption(opt, msg) {
  const original = opt.textContent;
  opt.textContent = msg;
  opt.disabled = true;
  setTimeout(() => {
    opt.textContent = original;
    opt.disabled = false;
    closeShareMenu();
  }, 1200);
}

function buildShareUrl() {
  const url = new URL(window.location.href);
  const params = new URLSearchParams();
  if (lang !== 'en') params.set('lang', lang);
  if (currentYear != null) params.set('year', currentYear);
  const qs = params.toString();
  url.search = qs ? `?${qs}` : '';
  url.hash = '';
  return url.toString();
}

function emailResults() {
  const heading = document.getElementById('changes-heading').textContent || t('emailDefaultHeading');
  const summaryEl = document.querySelector('#overview-block .overview-summary');
  const summary = summaryEl ? summaryEl.textContent.trim() + '\n\n' : '';
  const body = `${summary}${t('emailViewFull')}\n${buildShareUrl()}`;
  window.location.href =
    `mailto:?subject=${encodeURIComponent(t('emailSubjectPrefix') + heading)}` +
    `&body=${encodeURIComponent(body)}`;
}

// ── Print / Save as PDF ───────────────────────────────────────────────────────

// Lazy images that haven't loaded yet print blank — force + await them first.
function loadVisibleImages(root) {
  const pending = [...root.querySelectorAll('.section-card:not(.is-hidden) img')]
    .filter(img => !img.complete)
    .map(img => {
      img.loading = 'eager';
      return new Promise(res => {
        img.addEventListener('load', res, { once: true });
        img.addEventListener('error', res, { once: true });
      });
    });
  return Promise.race([
    Promise.all(pending),
    new Promise(res => setTimeout(res, 3000)),
  ]);
}

async function printResults(opt) {
  const section = document.getElementById('changes-section');
  const original = opt.textContent;
  opt.textContent = t('sharePreparing');
  opt.disabled = true;
  try {
    await loadVisibleImages(section);
    closeShareMenu();
    // A print stylesheet (@media print) hides everything but the results, then
    // the browser's print dialog lets the user "Save as PDF".
    window.print();
  } finally {
    opt.textContent = original;
    opt.disabled = false;
  }
}

// ── Back-to-top button ────────────────────────────────────────────────────────

function initScrollTop() {
  const btn = document.getElementById('scroll-top');
  if (!btn) return;

  const update = () => {
    const heading = document.getElementById('changes-heading');
    const section = document.getElementById('changes-section');
    const show = section && !section.hidden && heading
      && heading.getBoundingClientRect().bottom < 0;
    btn.hidden = !show;
  };

  window.addEventListener('scroll', () => requestAnimationFrame(update), { passive: true });
  window.addEventListener('resize', update);
  btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Boot ──────────────────────────────────────────────────────────────────────

// Guarded so this module can be `require`d in Node (tests) without a DOM.
if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    initAccordion();
    initResultsControls();
    initScrollTop();
    init();
  });
}

// Export the pure helpers for unit testing under Node.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { resultPage, bucketBySubtopic, subtopicAnchorId, groupByChapter };
}

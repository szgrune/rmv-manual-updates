/**
 * Driver's Manual Updates by Year — frontend logic
 *
 * Data flow:
 *  1. Load data/manifest.json → populate year dropdown + pre-fetch accordion data
 *  2. User selects a year → fetch data/changes_{year}_to_{latest}.json → render
 */

const dataCache = {};

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
  const resp = await fetch('data/manifest.json');
  if (!resp.ok) throw new Error(`manifest.json fetch failed: ${resp.status}`);
  return resp.json();
}

// Subtopic outline is optional — if it can't be loaded, results still render
// grouped by chapter (every result falls into the "General" bucket).
async function loadSubtopics() {
  try {
    const resp = await fetch('data/subtopics.json');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    SUBTOPICS = await resp.json();
  } catch {
    SUBTOPICS = [];
  }
}

async function init() {
  const input = document.getElementById('year-input');
  const accordionLabel = document.getElementById('accordion-label');

  let manifest;
  try {
    manifest = await loadManifest();
  } catch (err) {
    showYearStatus('Could not load year data. Please refresh the page.', 'error');
    input.disabled = true;
    return;
  }

  // Subtopic outline backs the nested TOC and the per-subtopic grouping — load it
  // before any rendering so both the accordion and year views can use it.
  await loadSubtopics();

  const { manual_years: years, latest_year: latest } = manifest;

  // Update accordion label to use the actual latest year
  accordionLabel.textContent = `${latest} Updates`;

  // Editions the user can compare against — exclude the latest (that's what we
  // compare *to*). Sorted ascending so we can pick the most recent at-or-before.
  const fromYears = years.filter(year => year !== latest).sort((a, b) => a - b);

  // Pre-fetch accordion data (second-latest → latest)
  if (fromYears.length > 0) {
    const secondLatest = fromYears[fromYears.length - 1];
    loadChanges(secondLatest, latest).then(data => {
      if (data) renderAccordion(data);
    }).catch(() => {
      document.getElementById('accordion-content').innerHTML =
        `<p class="error-msg">Could not load ${latest} update data.</p>`;
    });
  }

  // Year input handler — evaluate on Enter or when the field loses focus
  const handler = () => handleYearInput(input.value, fromYears, latest);
  input.addEventListener('change', handler);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handler();
    }
  });

  // Reopen a shared view from the URL (?year=…).
  const yearParam = new URLSearchParams(window.location.search).get('year');
  if (yearParam) {
    input.value = yearParam;
    handleYearInput(yearParam, fromYears, latest);
  }
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadChanges(fromYear, toYear) {
  const key = `${fromYear}_${toYear}`;
  if (dataCache[key]) return dataCache[key];

  const resp = await fetch(`data/changes_${fromYear}_to_${toYear}.json`);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const data = await resp.json();
  dataCache[key] = data;
  return data;
}

// ── Year input ──────────────────────────────────────────────────────────────

async function handleYearInput(rawValue, fromYears, latestYear) {
  const changesSection = document.getElementById('changes-section');
  const value = rawValue.trim();

  // Anything that isn't a four-digit year is rejected outright.
  if (!/^\d{4}$/.test(value)) {
    changesSection.hidden = true;
    showYearStatus('Invalid Input', 'error');
    return;
  }

  const enteredYear = parseInt(value, 10);

  // Most recent edition at or before the entered year (e.g. 2009 → 2007).
  let fromYear = null;
  for (const y of fromYears) {
    if (y <= enteredYear) fromYear = y;
  }

  // Years before our oldest edition: warn, but still show the oldest edition's
  // updates as the closest available match.
  const beforeOldest = fromYear === null;
  if (beforeOldest) fromYear = fromYears[0];

  showYearStatus(beforeOldest
    ? `We only have manual data going back to ${fromYears[0]}.`
    : 'Loading…',
    beforeOldest ? 'error' : '');

  try {
    const data = await loadChanges(fromYear, latestYear);
    renderChanges(data, fromYear, latestYear);
    // Preserve the warning when we fell back to the oldest edition.
    if (!beforeOldest) showYearStatus('');
    // Reflect the view in the URL so it can be shared / reopened.
    currentYear = enteredYear;
    const url = new URL(window.location.href);
    url.search = `?year=${enteredYear}`;
    url.hash = '';
    history.replaceState(null, '', url.toString());
  } catch (err) {
    showYearStatus('Could not load update data. Please try again.', 'error');
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

  heading.textContent = `Changes Since ${fromYear}`;
  overviewBlock.innerHTML = '';
  sectionsList.innerHTML = '';
  resetResultsControls();

  // Summary paragraph (paraphrased, no direct quotes)
  if (data.overview) {
    overviewBlock.appendChild(buildSummaryParagraph(data.overview));
  }

  if (!data.sections || data.sections.length === 0) {
    sectionsList.innerHTML = '<p class="info-msg">No significant changes identified between these editions.</p>';
    changesSection.hidden = false;
    return;
  }

  const groups = groupByChapter(data.sections);

  // Table of contents inside the blue box (chapters + nested subtopics)
  overviewBlock.appendChild(buildTableOfContents(groups, idPrefix, SUBTOPICS));

  // Grouped change cards, split into subtopic subsections with anchored headings
  groups.forEach(group => {
    sectionsList.appendChild(buildChapterGroup(group, idPrefix, SUBTOPICS));
  });

  changesSection.hidden = false;
}

function renderAccordion(data) {
  const content = document.getElementById('accordion-content');
  content.innerHTML = '';

  if (!data.sections || data.sections.length === 0) {
    content.innerHTML = '<p class="info-msg">No significant changes identified for this period.</p>';
    return;
  }

  groupByChapter(data.sections).forEach(group => {
    content.appendChild(buildChapterGroup(group, 'accordion', SUBTOPICS));
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
  // "Rules of the Road" is highlighted by always sorting first; the rest keep
  // their natural chapter order.
  const rank = g => (g.chapter === 'Rules of the Road' ? -Infinity : g.chapter_num);
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
 * Outline-style table of contents inside the blue box: each chapter is a heading
 * with a nested list of its subtopics. Both levels autoscroll to their anchored
 * heading in the results. TOC entries are tagged so applyFilters can hide the ones
 * whose results all filtered out.
 */
function buildTableOfContents(groups, idPrefix, subtopics) {
  const nav = document.createElement('nav');
  nav.className = 'toc';
  nav.setAttribute('aria-label', 'Topic areas');

  const label = document.createElement('p');
  label.className = 'toc-label';
  label.textContent = 'Jump to a section:';
  nav.appendChild(label);

  const ul = document.createElement('ul');
  ul.className = 'toc-list';

  groups.forEach(group => {
    const targetId = groupAnchorId(idPrefix, group.chapter);
    const li = document.createElement('li');
    li.className = 'toc-chapter';
    li.appendChild(buildTocLink(targetId, group.chapter, 'toc-chapter-link'));

    // Nested subtopic links (skip the unnamed "General" bucket).
    const named = bucketBySubtopic(group.items, group.chapter_num, subtopics)
      .filter(b => b.title !== 'General' && b.items.length);
    if (named.length) {
      const subUl = document.createElement('ul');
      subUl.className = 'toc-sublist';
      named.forEach(bucket => {
        const subId = subtopicAnchorId(idPrefix, group.chapter, bucket.title);
        const subLi = document.createElement('li');
        subLi.appendChild(buildTocLink(subId, bucket.title, 'toc-sub-link'));
        subUl.appendChild(subLi);
      });
      li.appendChild(subUl);
    }

    ul.appendChild(li);
  });

  nav.appendChild(ul);
  return nav;
}

// Number of result pills shown per subtopic before "View All" is offered.
const SUBTOPIC_VISIBLE_LIMIT = 3;

function buildChapterGroup(group, idPrefix, subtopics) {
  const wrap = document.createElement('section');
  wrap.className = 'change-group';

  const heading = document.createElement('h3');
  heading.className = 'group-heading';
  heading.id = groupAnchorId(idPrefix, group.chapter);
  heading.textContent = group.chapter;
  wrap.appendChild(heading);

  bucketBySubtopic(group.items, group.chapter_num, subtopics).forEach(bucket => {
    const section = document.createElement('div');
    section.className = 'subtopic-section';

    if (bucket.title !== 'General') {
      const sub = document.createElement('h4');
      sub.className = 'subtopic-heading';
      sub.id = subtopicAnchorId(idPrefix, group.chapter, bucket.title);
      sub.textContent = bucket.title;
      section.appendChild(sub);
    }

    bucket.items.forEach(sec => section.appendChild(buildSectionCard(sec)));

    // "View All" / "Hide" toggle — only meaningful past the visible limit.
    if (bucket.items.length > SUBTOPIC_VISIBLE_LIMIT) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'view-toggle';
      btn.addEventListener('click', () => {
        section.dataset.expanded = section.dataset.expanded === 'true' ? 'false' : 'true';
        applySubtopicCollapse(section);
      });
      section.appendChild(btn);
    }

    wrap.appendChild(section);
    applySubtopicCollapse(section);
  });

  return wrap;
}

/**
 * Enforce the per-subtopic "first 3 results" rule on one subsection. The 4th
 * visible pill gets a gradient teaser (.result-teaser); the rest hide
 * (.result-overflow); a "View All" button reveals everything ("Hide" collapses
 * back). When a search/filter is active the cap is suspended so matches aren't
 * trapped behind the teaser. Re-run on render and whenever filters change.
 */
function applySubtopicCollapse(section) {
  const cards = [...section.querySelectorAll('.section-card')]
    .filter(c => !c.classList.contains('is-hidden'));
  cards.forEach(c => c.classList.remove('result-teaser', 'result-overflow'));

  const btn = section.querySelector('.view-toggle');
  const expanded = section.dataset.expanded === 'true';
  const capped = !filterActive && !expanded && cards.length > SUBTOPIC_VISIBLE_LIMIT;

  if (capped) {
    cards.forEach((c, i) => {
      if (i === SUBTOPIC_VISIBLE_LIMIT) c.classList.add('result-teaser');
      else if (i > SUBTOPIC_VISIBLE_LIMIT) c.classList.add('result-overflow');
    });
  }

  if (btn) {
    // Hide the button while filtering (all matches already shown) or when there's
    // nothing past the limit; otherwise label it for the current state.
    btn.hidden = filterActive || cards.length <= SUBTOPIC_VISIBLE_LIMIT;
    btn.textContent = expanded ? 'Hide' : 'View All';
  }
}

function buildCitationLink({ year, page }) {
  const a = document.createElement('a');
  a.className = 'citation-link';
  a.href = `manuals/Drivers_Manual_${year}.pdf#page=${page}`;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = `(p. ${page})`;
  a.title = `Open the ${year} Massachusetts Driver's Manual at page ${page}`;
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
    badge.textContent = sec.change_type;
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

  // Subtopic subsections: hide when empty, re-apply the (possibly suspended) cap,
  // and toggle the matching nested TOC link.
  sectionsList.querySelectorAll('.subtopic-section').forEach(section => {
    const visible = section.querySelector('.section-card:not(.is-hidden)') !== null;
    section.classList.toggle('is-hidden', !visible);
    const subHeading = section.querySelector('.subtopic-heading');
    const link = subHeading && tocLinkFor(subHeading.id);
    if (link) link.closest('li').classList.toggle('is-hidden', !visible);
    if (visible) applySubtopicCollapse(section);
  });

  sectionsList.querySelectorAll('.change-group').forEach(group => {
    const groupVisible = group.querySelector('.section-card:not(.is-hidden)') !== null;
    group.classList.toggle('is-hidden', !groupVisible);
    const heading = group.querySelector('.group-heading');
    const link = heading && tocLinkFor(heading.id);
    if (link) link.closest('.toc-chapter').classList.toggle('is-hidden', !groupVisible);
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
        flashOption(opt, 'Copied!');
      } catch {
        flashOption(opt, 'Copy failed');
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
  url.search = currentYear ? `?year=${currentYear}` : '';
  url.hash = '';
  return url.toString();
}

function emailResults() {
  const heading = document.getElementById('changes-heading').textContent || "Driver's Manual Updates";
  const summaryEl = document.querySelector('#overview-block .overview-summary');
  const summary = summaryEl ? summaryEl.textContent.trim() + '\n\n' : '';
  const body = `${summary}View the full results here:\n${buildShareUrl()}`;
  window.location.href =
    `mailto:?subject=${encodeURIComponent("MA Driver's Manual — " + heading)}` +
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
  opt.textContent = 'Preparing…';
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

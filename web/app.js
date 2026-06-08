/**
 * Driver's Manual Updates by Year — frontend logic
 *
 * Data flow:
 *  1. Load data/manifest.json → populate year dropdown + pre-fetch accordion data
 *  2. User selects a year → fetch data/changes_{year}_to_{latest}.json → render
 */

const dataCache = {};

// The year the user entered that produced the currently shown results — backs the
// shareable URL, the email body, and the PDF filename.
let currentYear = null;

// ── Manifest / startup ────────────────────────────────────────────────────────

async function loadManifest() {
  const resp = await fetch('data/manifest.json');
  if (!resp.ok) throw new Error(`manifest.json fetch failed: ${resp.status}`);
  return resp.json();
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

  // Table of contents inside the blue box
  overviewBlock.appendChild(buildTableOfContents(groups, idPrefix));

  // Grouped change cards with anchored headings
  groups.forEach(group => {
    sectionsList.appendChild(buildChapterGroup(group, idPrefix));
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
  // "Rules of the Road" is highlighted by always sorting first; the rest keep
  // their natural chapter order.
  const rank = g => (g.chapter === 'Rules of the Road' ? -Infinity : g.chapter_num);
  return [...groups.values()].sort((a, b) => rank(a) - rank(b));
}

function groupAnchorId(prefix, chapter) {
  const slug = chapter.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  return `${prefix}-group-${slug}`;
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

function buildTableOfContents(groups, idPrefix) {
  const nav = document.createElement('nav');
  nav.className = 'toc';
  nav.setAttribute('aria-label', 'Topic areas');

  const label = document.createElement('p');
  label.className = 'toc-label';
  label.textContent = 'Jump to a topic area:';
  nav.appendChild(label);

  const ul = document.createElement('ul');
  ul.className = 'toc-list';

  groups.forEach(group => {
    const targetId = groupAnchorId(idPrefix, group.chapter);
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = `#${targetId}`;
    a.textContent = group.chapter;
    a.addEventListener('click', (e) => {
      e.preventDefault();
      scrollToHeading(targetId);
    });
    li.appendChild(a);
    ul.appendChild(li);
  });

  nav.appendChild(ul);
  return nav;
}

function buildChapterGroup(group, idPrefix) {
  const wrap = document.createElement('section');
  wrap.className = 'change-group';

  const heading = document.createElement('h3');
  heading.className = 'group-heading';
  heading.id = groupAnchorId(idPrefix, group.chapter);
  heading.textContent = group.chapter;
  wrap.appendChild(heading);

  group.items.forEach(sec => {
    wrap.appendChild(buildSectionCard(sec));
  });

  return wrap;
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

function buildSectionCard(sec) {
  const card = document.createElement('div');
  card.className = 'section-card';

  // Filterable metadata (used by applyFilters): change type + searchable text.
  card.dataset.type = sec.change_type || '';
  card.dataset.search = [sec.title, sec.description, ...(sec.bullets || [])]
    .filter(Boolean).join(' ').toLowerCase();

  // Header: title + badge
  const header = document.createElement('div');
  header.className = 'card-header';

  const title = document.createElement('h4');
  title.textContent = sec.title || 'Update';
  header.appendChild(title);

  if (sec.change_type) {
    const badge = document.createElement('span');
    badge.className = `badge badge-${sec.change_type}`;
    badge.textContent = sec.change_type;
    header.appendChild(badge);
  }

  card.appendChild(header);

  // Description
  if (sec.description) {
    const desc = document.createElement('p');
    desc.className = 'section-description';
    desc.textContent = sec.description;
    card.appendChild(desc);
  }

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
    card.appendChild(ul);
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

    card.appendChild(gallery);
  }

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
  const empty = document.getElementById('results-empty');
  if (empty) empty.hidden = true;
  closeShareMenu();
}

/**
 * Live ctrl+F-style filtering of the rendered results. Combines a text search
 * (substring over each card's title/description/bullets) with the change-type
 * checkboxes (OR among checked types; no checkboxes = show all). Chapter groups
 * and their table-of-contents entries hide when none of their cards match.
 */
function applyFilters() {
  const sectionsList = document.getElementById('sections-list');
  if (!sectionsList) return;

  const query = (document.getElementById('results-search').value || '').trim().toLowerCase();
  const activeTypes = [...document.querySelectorAll('#results-filters input:checked')]
    .map(cb => cb.value);

  let anyVisible = false;
  sectionsList.querySelectorAll('.section-card').forEach(card => {
    const typeOk = activeTypes.length === 0 || activeTypes.includes(card.dataset.type);
    const textOk = !query || (card.dataset.search || '').includes(query);
    const visible = typeOk && textOk;
    card.classList.toggle('is-hidden', !visible);
    if (visible) anyVisible = true;
  });

  const toc = document.getElementById('overview-block');
  sectionsList.querySelectorAll('.change-group').forEach(group => {
    const groupVisible = group.querySelector('.section-card:not(.is-hidden)') !== null;
    group.classList.toggle('is-hidden', !groupVisible);
    const heading = group.querySelector('.group-heading');
    if (heading && toc) {
      const link = toc.querySelector(`.toc-list a[href="#${heading.id}"]`);
      if (link) link.closest('li').classList.toggle('is-hidden', !groupVisible);
    }
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

document.addEventListener('DOMContentLoaded', () => {
  initAccordion();
  initResultsControls();
  initScrollTop();
  init();
});

/**
 * Driver's Manual Updates by Year — frontend logic
 *
 * Data flow:
 *  1. Load data/manifest.json → populate year dropdown + pre-fetch accordion data
 *  2. User selects a year → fetch data/changes_{year}_to_{latest}.json → render
 */

const dataCache = {};

// ── Manifest / startup ────────────────────────────────────────────────────────

async function loadManifest() {
  const resp = await fetch('data/manifest.json');
  if (!resp.ok) throw new Error(`manifest.json fetch failed: ${resp.status}`);
  return resp.json();
}

async function init() {
  const select = document.getElementById('year-select');
  const accordionLabel = document.getElementById('accordion-label');

  let manifest;
  try {
    manifest = await loadManifest();
  } catch (err) {
    showYearStatus('Could not load year data. Please refresh the page.', 'error');
    select.innerHTML = '<option value="" disabled selected>Unavailable</option>';
    return;
  }

  const { manual_years: years, latest_year: latest } = manifest;

  // Update accordion label to use the actual latest year
  accordionLabel.textContent = `${latest} Updates`;

  // Populate dropdown — exclude the latest year (that's the edition we compare against)
  select.innerHTML = '<option value="" disabled selected>Select a year…</option>';
  years.filter(year => year !== latest).forEach(year => {
    const opt = document.createElement('option');
    opt.value = year;
    opt.textContent = year;
    select.appendChild(opt);
  });
  select.disabled = false;

  // Pre-fetch accordion data (second-latest → latest)
  const priorYears = years.filter(y => y !== latest);
  if (priorYears.length > 0) {
    const secondLatest = priorYears[priorYears.length - 1];
    loadChanges(secondLatest, latest).then(data => {
      if (data) renderAccordion(data);
    }).catch(() => {
      document.getElementById('accordion-content').innerHTML =
        '<p class="error-msg">Could not load 2026 update data.</p>';
    });
  }

  // Year selection handler
  select.addEventListener('change', () => {
    const selectedYear = parseInt(select.value, 10);
    handleYearSelect(selectedYear, latest);
  });
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

// ── Year selection ────────────────────────────────────────────────────────────

async function handleYearSelect(selectedYear, latestYear) {
  const select = document.getElementById('year-select');
  const changesSection = document.getElementById('changes-section');

  if (selectedYear === latestYear) {
    changesSection.hidden = false;
    document.getElementById('changes-heading').textContent = `Changes Since ${selectedYear}`;
    document.getElementById('overview-block').innerHTML =
      '<p class="info-msg">You selected the most current manual year. No updates to display.</p>';
    document.getElementById('sections-list').innerHTML = '';
    showYearStatus('');
    return;
  }

  showYearStatus('Loading…');
  select.disabled = true;

  try {
    const data = await loadChanges(selectedYear, latestYear);
    renderChanges(data, selectedYear, latestYear);
    showYearStatus('');
  } catch (err) {
    showYearStatus('Could not load update data. Please try again.', 'error');
    changesSection.hidden = true;
  } finally {
    select.disabled = false;
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
  return [...groups.values()].sort((a, b) => a.chapter_num - b.chapter_num);
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
      const target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      target.classList.add('group-flash');
      setTimeout(() => target.classList.remove('group-flash'), 1400);
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

function buildSectionCard(sec) {
  const card = document.createElement('div');
  card.className = 'section-card';

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

  // Bullets
  if (sec.bullets && sec.bullets.length > 0) {
    const ul = document.createElement('ul');
    ul.className = 'section-bullets';
    sec.bullets.forEach(bullet => {
      const li = document.createElement('li');
      li.textContent = bullet;
      ul.appendChild(li);
    });
    card.appendChild(ul);
  }

  // Images
  if (sec.images && sec.images.length > 0) {
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

      card.appendChild(figure);
    });
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
  init();
});

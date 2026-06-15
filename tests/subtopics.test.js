/**
 * Unit tests for the pure subtopic-bucketing helpers in web/app.js.
 * Run: node tests/subtopics.test.js   (no dependencies)
 */
const assert = require('node:assert');
const { resultPage, bucketBySubtopic, subtopicAnchorId } = require('../web/app.js');

let passed = 0;
function test(name, fn) {
  fn();
  passed++;
  console.log(`  ok  ${name}`);
}

// Mirror of the curated ch.4 outline (a subset is enough to exercise the logic).
const SUBTOPICS = [
  { chapter_num: 4, page: 87, title: 'Speed Limits' },
  { chapter_num: 4, page: 88, title: 'Traffic Signals' },
  { chapter_num: 4, page: 96, title: 'Pavement Markings' },
];

const sec = (page) => ({ citations: page == null ? [] : [{ year: 2026, page }] });

// ── resultPage ────────────────────────────────────────────────────────────────
test('resultPage returns the minimum citation page', () => {
  assert.strictEqual(resultPage({ citations: [{ page: 90 }, { page: 87 }, { page: 91 }] }), 87);
});

test('resultPage returns null when there are no page citations', () => {
  assert.strictEqual(resultPage({ citations: [] }), null);
  assert.strictEqual(resultPage({}), null);
  assert.strictEqual(resultPage({ citations: [{ year: 2026 }] }), null);
});

// ── bucketBySubtopic ──────────────────────────────────────────────────────────
test('bucketBySubtopic places a result under the nearest preceding heading', () => {
  const buckets = bucketBySubtopic([sec(89)], 4, SUBTOPICS);
  assert.deepStrictEqual(buckets.map(b => b.title), ['Traffic Signals']);
});

test('bucketBySubtopic puts a no-citation result in a leading General bucket', () => {
  const buckets = bucketBySubtopic([sec(null), sec(89)], 4, SUBTOPICS);
  assert.strictEqual(buckets[0].title, 'General');
  assert.strictEqual(buckets[0].items.length, 1);
});

test('bucketBySubtopic puts a pre-first-heading result in General', () => {
  const buckets = bucketBySubtopic([sec(80)], 4, SUBTOPICS);
  assert.strictEqual(buckets[0].title, 'General');
});

test('bucketBySubtopic preserves page order and drops empty subtopics', () => {
  const buckets = bucketBySubtopic([sec(99), sec(87), sec(89)], 4, SUBTOPICS);
  assert.deepStrictEqual(buckets.map(b => b.title),
    ['Speed Limits', 'Traffic Signals', 'Pavement Markings']);
});

test('bucketBySubtopic with no config returns one General bucket', () => {
  const buckets = bucketBySubtopic([sec(89), sec(99)], 4, []);
  assert.strictEqual(buckets.length, 1);
  assert.strictEqual(buckets[0].title, 'General');
  assert.strictEqual(buckets[0].items.length, 2);
});

// ── subtopicAnchorId ──────────────────────────────────────────────────────────
test('subtopicAnchorId is slugified and unique per chapter + subtopic', () => {
  const a = subtopicAnchorId('changes-2007', 'Rules of the Road', 'Traffic Signals');
  const b = subtopicAnchorId('changes-2007', 'Safety First', 'Sharing the Road');
  const c = subtopicAnchorId('changes-2007', 'Rules of the Road', 'Sharing the Road');
  assert.strictEqual(a, 'changes-2007-sub-rules-of-the-road-traffic-signals');
  assert.notStrictEqual(b, c);            // same subtopic, different chapter → distinct
  assert.ok(/^[a-z0-9-]+$/.test(a));      // slug-safe
});

// ── collapse threshold (mirrors SUBTOPIC_VISIBLE_LIMIT logic in applySubtopicCollapse) ──
test('collapse threshold: 4 results → 3 shown + 1 teaser, 0 when <= 3', () => {
  const LIMIT = 3;
  const layout = (n) => {
    const shown = [], teaser = [], overflow = [];
    for (let i = 0; i < n; i++) {
      if (i < LIMIT) shown.push(i);
      else if (i === LIMIT) teaser.push(i);
      else overflow.push(i);
    }
    return { shown: shown.length, teaser: teaser.length, overflow: overflow.length };
  };
  assert.deepStrictEqual(layout(4), { shown: 3, teaser: 1, overflow: 0 });
  assert.deepStrictEqual(layout(7), { shown: 3, teaser: 1, overflow: 3 });
  assert.deepStrictEqual(layout(3), { shown: 3, teaser: 0, overflow: 0 });
  assert.deepStrictEqual(layout(2), { shown: 2, teaser: 0, overflow: 0 });
});

console.log(`\n${passed} tests passed.`);

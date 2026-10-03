// node --test tests/sales_date.test.mjs
import assert from 'node:assert/strict';
import test from 'node:test';
import {draftSoldOn} from '../app/static/sales-date.js';

const today = '2026-10-04';

test('沒有日期的草稿用今天', () => {
  assert.equal(draftSoldOn({sold_on: '', items: []}, today), today);
});

test('空白草稿過了一天就換成今天', () => {
  assert.equal(draftSoldOn({sold_on: '2026-10-03', dated_on: '2026-10-03', items: []}, today), today);
  assert.equal(draftSoldOn({sold_on: '2026-10-03', items: []}, today), today);  // 舊版草稿沒有 dated_on
});

test('今天才選的補登日期保留', () => {
  assert.equal(draftSoldOn({sold_on: '2026-10-01', dated_on: today, items: []}, today), '2026-10-01');
});

test('有品項的草稿保留原日期（可能是前一天還沒送出的銷售）', () => {
  assert.equal(draftSoldOn({sold_on: '2026-10-03', dated_on: '2026-10-03', items: [{id: 1}]}, today), '2026-10-03');
});

test('送出結果待確認時不改日期', () => {
  assert.equal(draftSoldOn({sold_on: '2026-10-03', items: [], pending: {}}, today), '2026-10-03');
});

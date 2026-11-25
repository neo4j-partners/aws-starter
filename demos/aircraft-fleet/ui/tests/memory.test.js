// Tests for static/memory.js. Run with `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { MemoryView, NOTES } from '../static/memory.js';

// A minimal stand-in for the DOM. Setting innerHTML throws, so a test fails
// if an entry is ever parsed as HTML.
class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.className = '';
    this.textContent = '';
  }
  set innerHTML(_value) { throw new Error('innerHTML must not be set'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
}
const fakeDocument = { createElement: tagName => new FakeElement(tagName) };

function view() {
  return new MemoryView(fakeDocument, new FakeElement('ol'), new FakeElement('p'), new FakeElement('p'));
}

function shown(memory) {
  return memory.list.children.map(item => item.children.map(child => child.textContent));
}

const ENTRIES = [
  { kind: 'entity', id: 'e-1', type: 'AIRCRAFT', text: 'N12345', score: 0.9134 },
  { kind: 'preference', id: 'p-1', type: 'format', text: 'Prefers tables', score: null },
  { kind: 'fact', id: 'f-1', type: 'OPERATES', text: 'AC1001 OPERATES FL00001', score: 0.8 },
];

test('a new view shows the idle note and no entries', () => {
  const memory = view();

  assert.equal(memory.note.textContent, NOTES.idle);
  assert.equal(memory.count.textContent, 'No memory yet');
  assert.deepEqual(memory.list.children, []);
});

test('each recalled entry shows its kind, type, text, and score', () => {
  const memory = view();

  memory.show(ENTRIES);

  assert.deepEqual(shown(memory), [
    ['Entity · AIRCRAFT', 'N12345', 'Similarity 0.91'],
    ['Preference · format', 'Prefers tables'],
    ['Fact · OPERATES', 'AC1001 OPERATES FL00001', 'Similarity 0.80'],
  ]);
  assert.deepEqual(memory.list.children.map(item => item.className), [
    'memory-entry entity', 'memory-entry preference', 'memory-entry fact',
  ]);
  assert.equal(memory.note.textContent, '3 entries recalled for this question.');
  assert.equal(memory.count.textContent, '3 entries recalled');
});

test('markup in an entry stays text', () => {
  const memory = view();
  const text = '<img src=x onerror="alert(1)"> N12345';

  memory.show([{ kind: '<b>entity</b>', type: '<i>x</i>', text, score: null }]);

  assert.deepEqual(shown(memory), [['Entry · <i>x</i>', text]]);
  assert.equal(memory.list.children[0].className, 'memory-entry other');
});

test('an empty recall shows the no-recall note', () => {
  const memory = view();
  memory.show(ENTRIES);

  memory.show([]);

  assert.deepEqual(memory.list.children, []);
  assert.equal(memory.note.textContent, NOTES.none);
  assert.equal(memory.count.textContent, 'Nothing recalled');
});

test('entries without text and malformed events are dropped', () => {
  const memory = view();

  memory.show([null, { kind: 'entity', text: '  ' }, { kind: 'entity', text: 7 }, ENTRIES[0]]);
  assert.equal(memory.list.children.length, 1);

  memory.show('not a list');
  assert.equal(memory.note.textContent, NOTES.none);
});

test('a question that ends with no memory event shows the no-recall note', () => {
  const memory = view();
  memory.show(ENTRIES);

  memory.waiting();
  assert.equal(memory.note.textContent, NOTES.waiting);
  assert.deepEqual(memory.list.children, []);

  memory.finish();
  assert.equal(memory.note.textContent, NOTES.none);
});

test('finishing keeps the entries the question recalled', () => {
  const memory = view();
  memory.waiting();
  memory.show(ENTRIES);

  memory.finish();

  assert.equal(memory.list.children.length, 3);
  assert.equal(memory.note.textContent, '3 entries recalled for this question.');
});

test('New chat returns the view to the idle note', () => {
  const memory = view();
  memory.show(ENTRIES);

  memory.reset();

  assert.deepEqual(memory.list.children, []);
  assert.equal(memory.note.textContent, NOTES.idle);
});

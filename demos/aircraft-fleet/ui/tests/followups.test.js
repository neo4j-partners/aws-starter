// Tests for static/followups.js. Run with `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { renderFollowUps } from '../static/followups.js';

// A minimal stand-in for the DOM. Setting innerHTML throws, so a test fails
// if a question is ever parsed as HTML.
class FakeElement {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.textContent = '';
  }
  set innerHTML(_value) { throw new Error('innerHTML must not be set'); }
  append(...nodes) { this.children.push(...nodes); }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  click() { this.listeners.click?.(); }
}
const fakeDocument = { createElement: tagName => new FakeElement(tagName) };

function buttons(section) {
  return section.children[0].children.map(item => item.children[0]);
}

test('each question becomes a labelled button with its text', () => {
  const section = renderFollowUps(fakeDocument, ['Which aircraft?', 'What fault?'], () => {});

  assert.equal(section.tagName, 'section');
  assert.equal(section.attributes['aria-label'], 'Suggested follow-up questions');
  assert.deepEqual(buttons(section).map(button => [button.tagName, button.type, button.textContent]), [
    ['button', 'button', 'Which aircraft?'],
    ['button', 'button', 'What fault?'],
  ]);
});

test('markup in a question stays text', () => {
  const question = '<img src=x onerror="alert(1)"> Which tail?';

  const [button] = buttons(renderFollowUps(fakeDocument, [question], () => {}));

  assert.equal(button.textContent, question);
  assert.equal(button.children.length, 0);
});

test('a click asks that question', () => {
  const asked = [];
  const [, second] = buttons(renderFollowUps(fakeDocument, ['First?', 'Second?'], q => asked.push(q)));

  second.click();

  assert.deepEqual(asked, ['Second?']);
});

test('at most three questions are shown, and blanks and non-text are dropped', () => {
  const section = renderFollowUps(fakeDocument, [' ', 7, 'A?', null, 'B?', 'C?', 'D?'], () => {});

  assert.deepEqual(buttons(section).map(button => button.textContent), ['A?', 'B?', 'C?']);
});

for (const questions of [undefined, null, 'not a list', [], ['', '  ']]) {
  test(`nothing is shown for ${JSON.stringify(questions)}`, () => {
    assert.equal(renderFollowUps(fakeDocument, questions, () => {}), null);
  });
}

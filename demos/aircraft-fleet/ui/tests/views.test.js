// Tests for static/views.js. Run with `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ViewTabs } from '../static/views.js';

class FakeTab {
  constructor() {
    this.attributes = { 'aria-selected': 'false' };
    this.listeners = {};
    this.tabIndex = -1;
    this.focused = false;
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  focus() { this.focused = true; }
  click() { this.listeners.click(); }
  press(key) {
    const event = { key, prevented: false, preventDefault() { this.prevented = true; } };
    this.listeners.keydown(event);
    return event;
  }
}

function setup() {
  const tabs = [new FakeTab(), new FakeTab()];
  const panels = [{ inert: false }, { inert: true }];
  const changes = [];
  const views = new ViewTabs(tabs, panels, index => changes.push(index));
  return { tabs, panels, changes, views };
}

function state({ tabs, panels }) {
  return tabs.map((tab, index) => [tab.attributes['aria-selected'], tab.tabIndex, panels[index].inert]);
}

test('clicking the memory tab shows the memory view and hides the evidence view', () => {
  const page = setup();

  page.tabs[1].click();

  assert.deepEqual(state(page), [['false', -1, true], ['true', 0, false]]);
  assert.deepEqual(page.changes, [1]);
});

test('clicking current evidence switches back', () => {
  const page = setup();
  page.tabs[1].click();

  page.tabs[0].click();

  assert.deepEqual(state(page), [['true', 0, false], ['false', -1, true]]);
  assert.deepEqual(page.changes, [1, 0]);
});

test('arrow keys wrap between the tabs and move focus', () => {
  const page = setup();

  assert.equal(page.tabs[0].press('ArrowRight').prevented, true);
  assert.equal(page.views.active, 1);
  assert.equal(page.tabs[1].focused, true);

  page.tabs[1].press('ArrowRight');
  assert.equal(page.views.active, 0);

  page.tabs[0].press('ArrowLeft');
  assert.equal(page.views.active, 1);
});

test('Home and End pick the first and last tab', () => {
  const page = setup();

  page.tabs[0].press('End');
  assert.equal(page.views.active, 1);

  page.tabs[1].press('Home');
  assert.equal(page.views.active, 0);
});

test('other keys are left alone', () => {
  const page = setup();

  const event = page.tabs[0].press('Enter');

  assert.equal(event.prevented, false);
  assert.deepEqual(page.changes, []);
});

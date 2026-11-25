// The Memory view: the long-term memory entries recalled for one question.
// Every entry field is set as text, never parsed as HTML.
export const KIND_LABELS = { entity: 'Entity', preference: 'Preference', fact: 'Fact' };
export const NOTES = {
  idle: 'The memory recalled for each question appears here.',
  waiting: 'Waiting for the memory recalled for this question.',
  none: 'No memory was recalled for this question.',
};

function recalled(count) {
  return `${count} ${count === 1 ? 'entry' : 'entries'} recalled`;
}

export class MemoryView {
  constructor(doc, list, note, count) {
    this.doc = doc;
    this.list = list;
    this.note = note;
    this.count = count;
    this.shown = false;
    this.reset();
  }

  // Before the first question, and after New chat.
  reset() {
    this.setNote(NOTES.idle, 'No memory yet');
  }

  // A question started. Its recall has not arrived yet.
  waiting() {
    this.setNote(NOTES.waiting, 'Recalling memory');
  }

  // The question ended. With no memory event, nothing was recalled.
  finish() {
    if (!this.shown) this.show([]);
  }

  show(entries) {
    const kept = (Array.isArray(entries) ? entries : []).filter(
      entry => entry && typeof entry.text === 'string' && entry.text.trim(),
    );
    if (kept.length === 0) {
      this.setNote(NOTES.none, 'Nothing recalled');
      this.shown = true;
      return;
    }
    this.list.replaceChildren(...kept.map(entry => this.item(entry)));
    this.note.textContent = `${recalled(kept.length)} for this question.`;
    this.count.textContent = recalled(kept.length);
    this.shown = true;
  }

  item(entry) {
    const item = this.doc.createElement('li');
    item.className = `memory-entry ${KIND_LABELS[entry.kind] ? entry.kind : 'other'}`;
    const label = this.doc.createElement('span');
    label.className = 'memory-kind';
    const kind = KIND_LABELS[entry.kind] ?? 'Entry';
    label.textContent = typeof entry.type === 'string' && entry.type ? `${kind} · ${entry.type}` : kind;
    const text = this.doc.createElement('strong');
    text.textContent = entry.text;
    item.append(label, text);
    if (typeof entry.score === 'number') {
      const score = this.doc.createElement('span');
      score.className = 'memory-score';
      score.textContent = `Similarity ${entry.score.toFixed(2)}`;
      item.append(score);
    }
    return item;
  }

  setNote(note, count) {
    this.list.replaceChildren();
    this.note.textContent = note;
    this.count.textContent = count;
    this.shown = false;
  }
}

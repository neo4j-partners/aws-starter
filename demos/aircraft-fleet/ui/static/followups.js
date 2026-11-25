// The suggested follow-up questions under a finished answer.
export const MAX_FOLLOWUPS = 3;

// Build the follow-up list, or return null when there is nothing to show.
// Each question is set as text, never parsed as HTML. A click asks it.
export function renderFollowUps(doc, questions, ask) {
  const kept = (Array.isArray(questions) ? questions : [])
    .filter(question => typeof question === 'string' && question.trim())
    .slice(0, MAX_FOLLOWUPS);
  if (kept.length === 0) return null;
  const section = doc.createElement('section');
  section.className = 'followups';
  section.setAttribute('aria-label', 'Suggested follow-up questions');
  const list = doc.createElement('ul');
  for (const question of kept) {
    const item = doc.createElement('li');
    const button = doc.createElement('button');
    button.type = 'button';
    button.className = 'followup';
    button.textContent = question;
    button.addEventListener('click', () => ask(question));
    item.append(button);
    list.append(item);
  }
  section.append(list);
  return section;
}

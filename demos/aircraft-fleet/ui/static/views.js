// The tabs that switch the evidence panel between its views.
// Arrow keys, Home, and End move between the tabs and show the focused view.
// An inactive view stays laid out but is inert and invisible, so the graph
// canvas keeps its size while the memory view is shown.
export class ViewTabs {
  constructor(tabs, panels, onChange = () => {}) {
    this.tabs = tabs;
    this.panels = panels;
    this.onChange = onChange;
    this.active = 0;
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => this.show(index));
      tab.addEventListener('keydown', event => this.keydown(event, index));
    });
  }

  keydown(event, index) {
    const last = this.tabs.length - 1;
    const next = {
      ArrowRight: index === last ? 0 : index + 1,
      ArrowLeft: index === 0 ? last : index - 1,
      Home: 0,
      End: last,
    }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    this.show(next);
    this.tabs[next].focus();
  }

  show(index) {
    this.active = index;
    this.tabs.forEach((tab, position) => {
      const selected = position === index;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      this.panels[position].inert = !selected;
    });
    this.onChange(index);
  }
}

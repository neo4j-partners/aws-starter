import { d3ForceLayoutType, NVL } from '@neo4j-nvl/base';
import { ClickInteraction, DragNodeInteraction, PanInteraction, ZoomInteraction } from '@neo4j-nvl/interaction-handlers';

const kinds = {
  Aircraft: ['Aircraft', '#237053'],
  System: ['System', '#315c91'],
  Component: ['Component', '#83579a'],
  MaintenanceEvent: ['Maintenance event', '#ac532b'],
  Flight: ['Flight', '#267988'],
};

export class EvidenceGraph {
  constructor() {
    this.nodes = new Map();
    this.edges = new Map();
    this.canvas = document.getElementById('canvas');
    this.empty = document.getElementById('graph-empty');
    this.details = document.getElementById('node-details');
    this.count = document.getElementById('graph-count');
    this.fitButton = document.getElementById('fit');
    this.fitButton.addEventListener('click', () => this.fit());
  }

  add(graph) {
    if (!graph.nodes.length) return;
    for (const node of graph.nodes) this.nodes.set(node.id, node);
    for (const edge of graph.edges) this.edges.set(edge.id, edge);
    this.render();
  }

  select(graph) {
    this.selection = graph && {
      nodes: new Set(graph.nodes.map(node => node.id)),
      edges: new Set(graph.edges.map(edge => edge.id)),
    };
    this.details.hidden = true;
    if (this.nodes.size) {
      this.render();
      this.fit();
    }
  }

  fit() {
    const ids = this.selection?.nodes ?? this.nodes.keys();
    this.nvl?.fit([...ids]);
  }

  render() {
    const nodes = Array.from(this.nodes.values(), node => ({
      id: node.id,
      caption: node.label,
      color: !this.selection || this.selection.nodes.has(node.id) ? kinds[node.kind][1] : '#b5c3ba',
      size: node.kind === 'Aircraft' ? 28 : 20,
    }));
    const edges = Array.from(this.edges.values(), edge => ({
      id: edge.id, from: edge.from, to: edge.to,
      caption: edge.label.toLowerCase().replaceAll('_', ' '),
      color: !this.selection || this.selection.edges.has(edge.id) ? '#597264' : '#c6d0c7',
    }));
    try {
      if (this.nvl) {
        this.nvl.addAndUpdateElementsInGraph(nodes, edges);
      } else {
        this.nvl = new NVL(this.canvas, nodes, edges, {
          renderer: 'canvas',
          layout: d3ForceLayoutType,
          backgroundColor: '#f7faf7',
          allowDynamicMinZoom: true,
          disableWebWorkers: true,
        }, { onLayoutDone: () => this.fit() });
        this.interactions = [
          new PanInteraction(this.nvl), new ZoomInteraction(this.nvl), new DragNodeInteraction(this.nvl),
          new ClickInteraction(this.nvl, { onNodeClick: node => this.showNode(node.id), onCanvasClick: () => {
            this.details.hidden = true;
          } }),
        ];
      }
      this.empty.hidden = true;
      this.fitButton.disabled = false;
      this.count.textContent = `${nodes.length} ${nodes.length === 1 ? 'entity' : 'entities'} · ${edges.length} ${edges.length === 1 ? 'relationship' : 'relationships'}`;
    } catch (error) {
      console.error('Fleet graph could not render', error);
      this.empty.hidden = false;
      this.empty.querySelector('p').textContent = 'The graph could not be rendered in this browser.';
    }
  }

  showNode(id) {
    const node = this.nodes.get(id);
    const label = document.createElement('p');
    label.textContent = `${kinds[node.kind][0]} · ${id}`;
    const title = document.createElement('h3');
    title.textContent = node.label;
    this.details.replaceChildren(label, title);
    for (const [key, value] of Object.entries(node.details)) {
      const field = document.createElement('p');
      field.textContent = `${key[0].toUpperCase()}${key.slice(1).replaceAll('_', ' ')}: ${value}`;
      this.details.append(field);
    }
    this.details.hidden = false;
  }

  reset() {
    for (const interaction of this.interactions ?? []) interaction.destroy();
    this.nvl?.destroy();
    this.interactions = [];
    this.nvl = null;
    this.nodes.clear();
    this.edges.clear();
    this.selection = null;
    this.details.hidden = true;
    this.empty.hidden = false;
    this.empty.querySelector('p').textContent = 'Fleet evidence appears here as tools return results.';
    this.count.textContent = 'No evidence yet';
    this.fitButton.disabled = true;
  }
}

import { useRef, useEffect, useState, useMemo } from 'react';
import * as d3 from 'd3';

const COLORS = [
  '#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16',
  '#a855f7', '#22d3ee', '#fb923c', '#4ade80', '#f43f5e',
];
const HULL_FILL = COLORS.map(c => c + '10');
const HULL_STROKE = COLORS.map(c => c + '30');

const MAX_DIRECT = 200;

/* ── Aggregate large graphs into community summary nodes ──────────── */
function aggregateGraph(data) {
  if (!data || data.nodes.length <= MAX_DIRECT) return { ...data, _agg: false };

  const comms = {};
  const standalone = [];
  for (const n of data.nodes) {
    if (n.community_id == null) { standalone.push(n); continue; }
    const c = (comms[n.community_id] ??= { nodes: [], clients: 0, ports: 0, hubs: [] });
    c.nodes.push(n);
    c.clients += n.client_count || 0;
    c.ports += n.port_count || 0;
    if (n.is_hub) c.hubs.push(n.id);
  }

  const aggNodes = [...standalone];
  const remap = {};

  for (const [cid, cm] of Object.entries(comms)) {
    const hub = cm.hubs[0];
    const id = `community_${cid}`;
    aggNodes.push({
      id, name: hub ? `Hub: ${hub}` : `Community ${cid}`,
      community_id: +cid, is_hub: cm.hubs.length > 0, is_aggregate: true,
      member_count: cm.nodes.length, client_count: cm.clients, port_count: cm.ports,
      clients: [{ id, app_id: `${cm.nodes.length} QMs`, name: `${cm.clients} apps`, role: 'both' }],
      members: cm.nodes.map(n => n.id), local_queues: 0, remote_queues: 0, alias_queues: 0,
    });
    for (const n of cm.nodes) remap[n.id] = id;
  }

  const seen = new Set();
  const aggLinks = [];
  for (const l of data.links) {
    const s = remap[l.source] || l.source;
    const t = remap[l.target] || l.target;
    if (s === t) continue;
    const k = `${s}->${t}`;
    if (seen.has(k)) { const ex = aggLinks.find(e => e.id === k); if (ex) ex._count++; continue; }
    seen.add(k);
    aggLinks.push({ ...l, id: k, source: s, target: t, name: '', _count: 1, topology: 'aggregated' });
  }
  aggLinks.forEach(l => { l.name = `${l._count} channel${l._count > 1 ? 's' : ''}`; });

  return {
    nodes: aggNodes, links: aggLinks, _agg: true,
    summary: { ...data.summary, aggregated: true, original_nodes: data.nodes.length, original_edges: data.links.length, total_nodes: aggNodes.length, total_edges: aggLinks.length },
  };
}

/* ── ForceGraph Component ─────────────────────────────────────────── */
export default function ForceGraph({ data, width = 900, height = 600, title, onSelectNode, changeSet }) {
  const svgRef = useRef();
  const tipRef = useRef();
  const adjRef = useRef(new Map());
  const focusRef = useRef(null);
  const [focusedNode, setFocusedNode] = useState(null);
  const [focusedNeighbors, setFocusedNeighbors] = useState([]);
  const [focusedEdges, setFocusedEdges] = useState([]);

  const gd = useMemo(() => data ? aggregateGraph(data) : null, [data]);

  // Reset focus when data changes
  useEffect(() => { focusRef.current = null; setFocusedNode(null); setFocusedNeighbors([]); setFocusedEdges([]); }, [gd]);

  /* ── Main D3 effect ──────────────────────────────────────────────── */
  useEffect(() => {
    if (!gd?.nodes?.length) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const W = width, H = height;
    svg.attr('viewBox', `0 0 ${W} ${H}`);

    const defs = svg.append('defs');
    const g = svg.append('g');

    // Zoom
    const zoom = d3.zoom().scaleExtent([0.1, 6]).on('zoom', e => g.attr('transform', e.transform));
    svg.call(zoom);

    // Clone data
    const nodes = gd.nodes.map(d => ({ ...d }));
    const links = gd.links.map(d => ({ ...d }));
    const nMap = new Map(nodes.map(n => [n.id, n]));

    // Adjacency
    const adj = new Map();
    nodes.forEach(n => adj.set(n.id, new Set()));
    links.forEach(l => {
      const s = typeof l.source === 'object' ? l.source.id : l.source;
      const t = typeof l.target === 'object' ? l.target.id : l.target;
      adj.get(s)?.add(t); adj.get(t)?.add(s);
    });
    adjRef.current = adj;

    // Layout params
    const N = nodes.length;
    const small = N <= 30, med = N <= 100;
    const nodeR = d => {
      if (d.is_aggregate) return 45 + Math.min((d.member_count || 0) * 1.5, 25);
      const base = d.is_hub ? (small ? 46 : 36) : (small ? 36 : 26);
      return base + Math.min((d.client_count || 0) * 2, 10);
    };

    // Community-clustering targets
    const commIds = [...new Set(nodes.filter(n => n.community_id != null).map(n => n.community_id))];
    const cTargets = {};
    commIds.forEach((cid, i) => {
      const a = (2 * Math.PI * i) / (commIds.length || 1);
      const r = Math.min(W, H) * 0.22;
      cTargets[cid] = { x: W / 2 + Math.cos(a) * r, y: H / 2 + Math.sin(a) * r };
    });

    // Pre-index community → nodes
    const commNodes = {};
    nodes.forEach(n => { if (n.community_id != null) (commNodes[n.community_id] ??= []).push(n); });

    // Simulation
    const sim = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(d => d.id).distance(small ? 260 : med ? 160 : 110).strength(0.4))
      .force('charge', d3.forceManyBody().strength(small ? -1100 : med ? -500 : -250).distanceMax(600))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide().radius(d => nodeR(d) + 12))
      .force('cx', d3.forceX(d => cTargets[d.community_id]?.x ?? W / 2).strength(commIds.length > 1 ? 0.08 : 0.03))
      .force('cy', d3.forceY(d => cTargets[d.community_id]?.y ?? H / 2).strength(commIds.length > 1 ? 0.08 : 0.03))
      .alphaDecay(N > 80 ? 0.045 : 0.025);

    // Defs — arrows
    COLORS.forEach((c, i) => {
      defs.append('marker').attr('id', `a${i}`).attr('viewBox', '0 -5 10 10')
        .attr('refX', 12).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
        .append('path').attr('d', 'M0,-4L10,0L0,4').attr('fill', c).attr('opacity', 0.7);
    });
    defs.append('marker').attr('id', 'a-bb').attr('viewBox', '0 -5 10 10')
      .attr('refX', 12).attr('refY', 0).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L10,0L0,4').attr('fill', '#fbbf24').attr('opacity', 0.8);
    // Glow
    const glow = defs.append('filter').attr('id', 'glow');
    glow.append('feGaussianBlur').attr('stdDeviation', '4').attr('result', 'blur');
    const fm = glow.append('feMerge'); fm.append('feMergeNode').attr('in', 'blur'); fm.append('feMergeNode').attr('in', 'SourceGraphic');

    // Layers
    const hullLayer = g.append('g');
    const linkGroup = g.append('g');
    const nodeGroup = g.append('g');

    /* ── Links ─────────────────────────────────────────────────────── */
    const edgeColor = d => {
      if (d.topology === 'backbone') return '#fbbf24';
      const sn = nMap.get(typeof d.source === 'object' ? d.source.id : d.source);
      return sn?.community_id != null ? COLORS[sn.community_id % COLORS.length] : '#4b5563';
    };
    const edgeW = d => d.topology === 'backbone' ? 3 : (d._count > 5 ? 2.5 : 1.5);
    const edgeDash = d => d.topology === 'backbone' ? '8,4' : 'none';
    const edgeMarker = d => {
      if (d.topology === 'backbone') return 'url(#a-bb)';
      const sn = nMap.get(typeof d.source === 'object' ? d.source.id : d.source);
      return sn?.community_id != null ? `url(#a${sn.community_id % COLORS.length})` : '';
    };

    const linkPath = linkGroup.selectAll('.lp').data(links).enter().append('path')
      .attr('class', 'lp').attr('fill', 'none')
      .attr('stroke', edgeColor).attr('stroke-width', edgeW)
      .attr('stroke-dasharray', edgeDash).attr('stroke-opacity', 0.45)
      .attr('marker-end', edgeMarker);

    // Invisible hover zones
    linkGroup.selectAll('.lh').data(links).enter().append('path')
      .attr('class', 'lh').attr('fill', 'none').attr('stroke', 'transparent').attr('stroke-width', 16).attr('cursor', 'pointer')
      .on('mouseenter', function (ev, d) {
        const sr = svgRef.current.getBoundingClientRect();
        const x = ev.clientX - sr.left + 12, y = ev.clientY - sr.top - 8;
        const s = typeof d.source === 'object' ? d.source.id : d.source;
        const t = typeof d.target === 'object' ? d.target.id : d.target;
        d3.select(tipRef.current)
          .style('display', 'block').style('left', x + 'px').style('top', y + 'px')
          .html(`<div class="font-mono text-[11px] font-bold text-white">${d.name || s + ' \u2192 ' + t}</div>
            <div class="text-gray-400 text-[10px] mt-0.5">${s} \u2192 ${t}</div>
            ${d.topology ? `<div class="mt-0.5"><span class="text-[10px] px-1.5 py-0.5 rounded ${d.topology === 'backbone' ? 'bg-amber-900/50 text-amber-300' : d.topology === 'spoke_to_hub' ? 'bg-emerald-900/50 text-emerald-300' : d.topology === 'hub_to_spoke' ? 'bg-blue-900/50 text-blue-300' : 'bg-gray-800 text-gray-400'}">${d.topology}</span></div>` : ''}
            ${d.flows?.length ? `<div class="text-[10px] text-gray-500 mt-1">${d.flows.slice(0, 3).join('<br/>')}${d.flows.length > 3 ? '<br/>+' + (d.flows.length - 3) + ' more' : ''}</div>` : ''}
            ${d._count ? `<div class="text-[10px] text-gray-500">${d._count} channels</div>` : ''}`);
        // Highlight
        d3.select(this.previousSibling).attr('stroke-opacity', 1).attr('stroke-width', 4);
      })
      .on('mouseleave', function () {
        d3.select(tipRef.current).style('display', 'none');
        d3.select(this.previousSibling).attr('stroke-opacity', 0.45).attr('stroke-width', edgeW);
      });

    // Label layer for focused-edge labels (no static labels — avoids overlap)
    const focusLabelGroup = g.append('g').attr('class', 'focus-labels');

    /* ── Nodes ─────────────────────────────────────────────────────── */
    const node = nodeGroup.selectAll('.ng').data(nodes).enter().append('g')
      .attr('class', 'ng').attr('cursor', 'pointer')
      .call(d3.drag()
        .on('start', (e, d) => { if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
        .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    // Focus helper
    function applyFocus(fNode) {
      focusLabelGroup.selectAll('*').remove();
      if (fNode) {
        const nb = adj.get(fNode.id) || new Set();
        nodeGroup.selectAll('.ng').transition().duration(250).attr('opacity', n => n.id === fNode.id || nb.has(n.id) ? 1 : 0.08);
        linkPath.transition().duration(250)
          .attr('stroke-opacity', l => { const s = l.source.id ?? l.source, t = l.target.id ?? l.target; return s === fNode.id || t === fNode.id ? 0.9 : 0.03; })
          .attr('stroke-width', l => { const s = l.source.id ?? l.source, t = l.target.id ?? l.target; return (s === fNode.id || t === fNode.id) ? 3.5 : 0.5; });
        // Show channel names on focused edges
        const focusLinks = links.filter(l => {
          const s = l.source.id ?? l.source, t = l.target.id ?? l.target;
          return s === fNode.id || t === fNode.id;
        });
        focusLinks.forEach(l => {
          if (!l.name) return;
          const mx = (l.source.x + l.target.x) / 2;
          const my = (l.source.y + l.target.y) / 2;
          // Offset perpendicular to avoid stacking
          const dx = l.target.x - l.source.x, dy = l.target.y - l.source.y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 1;
          const ox = (-dy / dist) * 14, oy = (dx / dist) * 14;
          const tw = Math.min(l.name.length * 5.5 + 10, 120);
          focusLabelGroup.append('rect')
            .attr('x', mx + ox - tw / 2).attr('y', my + oy - 8)
            .attr('width', tw).attr('height', 14).attr('rx', 3)
            .attr('fill', '#1f2937').attr('fill-opacity', 0.92);
          focusLabelGroup.append('text')
            .attr('x', mx + ox).attr('y', my + oy + 3)
            .attr('text-anchor', 'middle').attr('font-size', 7.5)
            .attr('font-family', 'ui-monospace,monospace').attr('fill', '#d1d5db')
            .text(l.name.length > 22 ? l.name.slice(0, 20) + '..' : l.name);
        });
      } else {
        nodeGroup.selectAll('.ng').transition().duration(250).attr('opacity', 1);
        linkPath.transition().duration(250).attr('stroke-opacity', 0.45).attr('stroke-width', edgeW);
      }
    }

    // Click
    node.on('click', (ev, d) => {
      ev.stopPropagation();
      const was = focusRef.current?.id === d.id;
      const nf = was ? null : d;
      focusRef.current = nf;
      setFocusedNode(nf);
      setFocusedNeighbors(nf ? [...(adj.get(d.id) || [])] : []);
      // Collect edge data for focus panel
      if (nf) {
        const nodeEdges = links.filter(l => {
          const s = l.source.id ?? l.source, t = l.target.id ?? l.target;
          return s === d.id || t === d.id;
        }).map(l => ({
          name: l.name, topology: l.topology || 'direct',
          from: l.source.id ?? l.source, to: l.target.id ?? l.target,
          flows: l.flows || [],
        }));
        setFocusedEdges(nodeEdges);
      } else {
        setFocusedEdges([]);
      }
      applyFocus(nf);
      if (onSelectNode) onSelectNode(nf || d);
    });
    svg.on('click', () => { focusRef.current = null; setFocusedNode(null); setFocusedNeighbors([]); setFocusedEdges([]); applyFocus(null); });

    // Draw each node
    node.each(function (d) {
      const el = d3.select(this);
      const r = nodeR(d);
      const cid = d.community_id ?? 0;
      const col = COLORS[cid % COLORS.length];
      const isNew = changeSet?.newNodeIds?.has(d.id);
      const isShared = changeSet?.sharedNodeIds?.has(d.id);
      const deg = adj.get(d.id)?.size || 0;

      // Hub glow
      if (d.is_hub && !d.is_aggregate) {
        el.append('circle').attr('r', r + 8).attr('fill', 'none')
          .attr('stroke', '#fbbf24').attr('stroke-width', 2.5).attr('stroke-dasharray', '6,3').attr('opacity', 0.6).attr('filter', 'url(#glow)');
      }
      // New ring
      if (isNew) {
        el.append('circle').attr('r', r + 5).attr('fill', 'none').attr('stroke', '#10b981').attr('stroke-width', 2.5).attr('opacity', 0.8);
      }
      // Shared ring
      if (isShared) {
        el.append('circle').attr('r', r + 5).attr('fill', 'none').attr('stroke', '#ef4444').attr('stroke-width', 2).attr('stroke-dasharray', '4,2').attr('opacity', 0.8);
      }

      // Main circle
      el.append('circle').attr('r', r)
        .attr('fill', d.is_aggregate ? col + '20' : col + '15')
        .attr('stroke', isNew ? '#10b981' : isShared ? '#ef4444' : col)
        .attr('stroke-width', d.is_hub ? 3 : (isNew || isShared) ? 2.5 : 1.5);

      // Name
      const nm = d.id.length > 18 ? d.id.slice(0, 16) + '..' : d.id;
      el.append('text').text(nm).attr('text-anchor', 'middle')
        .attr('dy', deg > 0 ? -6 : 2)
        .attr('font-size', d.is_hub ? (small ? 13 : 11) : (small ? 11 : 10))
        .attr('font-weight', 700).attr('font-family', 'ui-monospace,monospace').attr('fill', '#f3f4f6');

      // Connection count
      if (deg > 0) {
        el.append('text').text(`${deg} conn`).attr('text-anchor', 'middle').attr('dy', 7)
          .attr('font-size', 8).attr('fill', '#9ca3af');
      }

      // Apps summary
      const cl = d.clients || [];
      if (cl.length > 0 && cl.length <= 3 && (small || d.is_aggregate)) {
        cl.forEach((c, i) => {
          el.append('text').text(`${c.app_id} (${c.role?.[0]?.toUpperCase() || '?'})`)
            .attr('text-anchor', 'middle').attr('dy', 19 + i * 11)
            .attr('font-size', 8).attr('fill', '#9ca3af').attr('font-family', 'ui-monospace,monospace');
        });
      } else if (d.client_count > 0 && cl.length > 3) {
        el.append('text').text(`${d.client_count} apps`).attr('text-anchor', 'middle').attr('dy', 19)
          .attr('font-size', 8).attr('fill', '#9ca3af');
      }

      // Queue badge
      if ((d.port_count || 0) > 0 && !d.is_aggregate) {
        const bx = r * 0.65, by = -r + 10;
        el.append('circle').attr('cx', bx).attr('cy', by).attr('r', 10).attr('fill', '#1f2937').attr('stroke', '#4b5563');
        el.append('text').text(d.port_count).attr('x', bx).attr('y', by + 3.5)
          .attr('text-anchor', 'middle').attr('font-size', 8).attr('font-weight', 600).attr('fill', '#d1d5db');
      }

      // Top badge: HUB / NEW / SHARED / ISOLATED
      if (d.is_hub && !d.is_aggregate) {
        el.append('rect').attr('x', -16).attr('y', -r - 20).attr('width', 32).attr('height', 14).attr('rx', 3).attr('fill', '#78350f');
        el.append('text').text('HUB').attr('text-anchor', 'middle').attr('dy', -r - 10)
          .attr('font-size', 9).attr('font-weight', 700).attr('fill', '#fbbf24').attr('letter-spacing', '1.5px');
      } else if (isNew) {
        el.append('rect').attr('x', -15).attr('y', -r - 20).attr('width', 30).attr('height', 14).attr('rx', 3).attr('fill', '#064e3b');
        el.append('text').text('NEW').attr('text-anchor', 'middle').attr('dy', -r - 10)
          .attr('font-size', 9).attr('font-weight', 700).attr('fill', '#10b981');
      } else if (isShared) {
        el.append('rect').attr('x', -26).attr('y', -r - 20).attr('width', 52).attr('height', 14).attr('rx', 3).attr('fill', '#7f1d1d');
        el.append('text').text('SHARED').attr('text-anchor', 'middle').attr('dy', -r - 10)
          .attr('font-size', 8).attr('font-weight', 700).attr('fill', '#fca5a5');
      } else if (d.is_isolated && deg === 0) {
        el.append('rect').attr('x', -32).attr('y', -r - 20).attr('width', 64).attr('height', 14).attr('rx', 3).attr('fill', '#1e1b4b');
        el.append('text').text('LOCAL ONLY').attr('text-anchor', 'middle').attr('dy', -r - 10)
          .attr('font-size', 8).attr('font-weight', 700).attr('fill', '#818cf8');
      }

      // Community label
      if (d.community_id != null && !d.is_aggregate) {
        el.append('text').text(`C${d.community_id}`).attr('text-anchor', 'middle').attr('dy', r + 14)
          .attr('font-size', 8).attr('fill', '#6b7280');
      }
    });

    /* ── Tick ──────────────────────────────────────────────────────── */
    const hullLine = d3.line().curve(d3.curveCatmullRomClosed);
    let tick = 0;

    sim.on('tick', () => {
      // Community hulls (every 3rd tick to save perf, only if communities exist)
      if (commIds.length > 0 && tick % 3 === 0) {
        hullLayer.selectAll('*').remove();
        for (const cid of commIds) {
          const ns = commNodes[cid];
          if (!ns || ns.length < 3) continue;
          const pts = ns.map(n => [n.x, n.y]);
          const hull = d3.polygonHull(pts);
          if (!hull) continue;
          const cent = d3.polygonCentroid(hull);
          const pad = 50;
          const exp = hull.map(p => {
            const dx = p[0] - cent[0], dy = p[1] - cent[1];
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            return [p[0] + dx / dist * pad, p[1] + dy / dist * pad];
          });
          const ci = cid % COLORS.length;
          hullLayer.append('path').attr('d', hullLine(exp))
            .attr('fill', HULL_FILL[ci]).attr('stroke', HULL_STROKE[ci]).attr('stroke-width', 1.5);
          // Watermark label
          hullLayer.append('text').attr('x', cent[0]).attr('y', cent[1])
            .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
            .attr('font-size', Math.min(28, ns.length * 3 + 12)).attr('font-weight', 800)
            .attr('fill', COLORS[ci]).attr('opacity', 0.08).text(`C${cid}`);
        }
      }
      tick++;

      // Link paths
      linkPath.attr('d', d => {
        const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const dr = dist * 0.8;
        const sr = nodeR(d.source), tr = nodeR(d.target);
        return `M${d.source.x + dx * sr / dist},${d.source.y + dy * sr / dist}A${dr},${dr} 0 0,1 ${d.target.x - dx * tr / dist},${d.target.y - dy * tr / dist}`;
      });
      linkGroup.selectAll('.lh').attr('d', d => {
        const dx = d.target.x - d.source.x, dy = d.target.y - d.source.y;
        const dr = Math.sqrt(dx * dx + dy * dy) * 0.8;
        return `M${d.source.x},${d.source.y}A${dr},${dr} 0 0,1 ${d.target.x},${d.target.y}`;
      });
      // (static labels removed — shown on focus/hover instead)
      node.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // Zoom to fit
    const fitZoom = () => {
      const b = g.node().getBBox();
      if (!b.width) return;
      const p = 50;
      const s = Math.min(W / (b.width + p * 2), H / (b.height + p * 2), 1.5);
      const tx = W / 2 - (b.x + b.width / 2) * s, ty = H / 2 - (b.y + b.height / 2) * s;
      svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(s));
    };
    sim.on('end', fitZoom);
    setTimeout(fitZoom, 1200);

    return () => sim.stop();
  }, [gd, width, height, changeSet]);

  const isAgg = gd?._agg;

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl overflow-hidden relative">
      {title && (
        <div className="px-4 py-2.5 border-b border-gray-800 flex items-center justify-between bg-gray-900/80">
          <span className="text-sm font-semibold text-gray-200">{title}</span>
          <span className="text-xs text-gray-500">
            {isAgg
              ? `${gd.summary.original_nodes} QMs in ${gd.summary.total_nodes} groups`
              : gd?.summary
                ? `${gd.summary.total_nodes} QMs \u00b7 ${gd.summary.total_edges} ch \u00b7 ${gd.summary.total_clients || 0} apps`
                : ''}
            <span className="text-gray-600 ml-2">scroll=zoom, drag=pan, click=focus</span>
          </span>
        </div>
      )}
      <svg ref={svgRef} className="w-full bg-gray-950/60" style={{ height }} />
      {/* Tooltip */}
      <div ref={tipRef} className="absolute pointer-events-none bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 shadow-xl z-50 max-w-xs" style={{ display: 'none' }} />
      {/* Focus panel */}
      {focusedNode && (
        <div className="absolute bottom-2 left-2 right-2 bg-gray-900/95 border border-gray-700 rounded-xl px-4 py-3 backdrop-blur-sm shadow-2xl max-h-[50%] overflow-y-auto">
          {/* Header row */}
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className="font-mono font-bold text-white text-sm">{focusedNode.id}</span>
            {focusedNode.is_hub && <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-400 font-bold">HUB</span>}
            {focusedNode.community_id != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">C{focusedNode.community_id}</span>}
            {changeSet?.newNodeIds?.has(focusedNode.id) && <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60 text-emerald-400 font-bold">NEW</span>}
            {changeSet?.sharedNodeIds?.has(focusedNode.id) && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/60 text-red-400 font-bold">SHARED QM</span>}
            {focusedNode.is_isolated && focusedNeighbors.length === 0 && <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-900/60 text-indigo-400 font-bold">LOCAL ONLY</span>}
            <span className="text-xs text-gray-500 ml-auto">
              <span className="text-white font-semibold">{focusedNeighbors.length}</span> connections
            </span>
          </div>

          {/* Summary counts */}
          <div className="flex gap-4 text-xs text-gray-400 mb-2">
            <span>Apps: <span className="text-white font-semibold">{focusedNode.client_count || 0}</span></span>
            <span>Queues: <span className="text-white font-semibold">{focusedNode.port_count || 0}</span></span>
            <span>
              L:<span className="text-emerald-400 font-semibold">{focusedNode.local_queues || 0}</span>{' '}
              R:<span className="text-amber-400 font-semibold">{focusedNode.remote_queues || 0}</span>{' '}
              A:<span className="text-purple-400 font-semibold">{focusedNode.alias_queues || 0}</span>
            </span>
          </div>

          {/* Connected QMs */}
          {focusedNeighbors.length > 0 && (
            <div className="text-xs text-gray-500 mb-2">
              Connected to: {focusedNeighbors.slice(0, 15).map((nid, i) => (
                <span key={nid} className="font-mono text-indigo-400">{i > 0 ? ', ' : ''}{nid}</span>
              ))}
              {focusedNeighbors.length > 15 && <span className="text-gray-600"> +{focusedNeighbors.length - 15} more</span>}
            </div>
          )}

          {/* Apps + their queues */}
          {focusedNode.clients?.length > 0 && (
            <div className="border-t border-gray-800 pt-2 mt-1">
              <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-1">
                Applications ({focusedNode.clients.length})
              </div>
              <div className="space-y-2">
                {focusedNode.clients.slice(0, 8).map(c => {
                  const lq = c.queues?.filter(q => q.type === 'local') || [];
                  const rq = c.queues?.filter(q => q.type === 'remote') || [];
                  const aq = c.queues?.filter(q => q.type === 'alias') || [];
                  const xq = c.queues?.filter(q => q.type === 'transmission') || [];
                  return (
                    <div key={c.id} className="bg-gray-800/60 rounded-lg px-2.5 py-1.5">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono text-indigo-400 text-xs font-bold">{c.app_id}</span>
                        <span className="text-gray-500 text-[10px] truncate max-w-[120px]">{c.name}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          c.role === 'producer' ? 'bg-emerald-900/50 text-emerald-400' :
                          c.role === 'consumer' ? 'bg-amber-900/50 text-amber-400' :
                          'bg-purple-900/50 text-purple-400'
                        }`}>{c.role}</span>
                      </div>
                      {/* Queue breakdown */}
                      <div className="space-y-0.5">
                        {lq.length > 0 && (
                          <div className="flex flex-wrap gap-1 items-start">
                            <span className="text-[9px] text-emerald-500 font-semibold w-10 shrink-0">LOCAL</span>
                            {lq.slice(0, 5).map((q, i) => (
                              <span key={i} className="font-mono text-[9px] bg-emerald-950/40 border border-emerald-900/30 px-1 py-0.5 rounded text-emerald-300 truncate max-w-[180px]">{q.name}</span>
                            ))}
                            {lq.length > 5 && <span className="text-[9px] text-gray-600">+{lq.length - 5}</span>}
                          </div>
                        )}
                        {rq.length > 0 && (
                          <div className="flex flex-wrap gap-1 items-start">
                            <span className="text-[9px] text-amber-500 font-semibold w-10 shrink-0">REMOTE</span>
                            {rq.slice(0, 5).map((q, i) => (
                              <span key={i} className="font-mono text-[9px] bg-amber-950/40 border border-amber-900/30 px-1 py-0.5 rounded text-amber-300 truncate max-w-[180px]" title={`${q.name} → ${q.remote_qm || '?'}${q.xmit_queue ? ' via ' + q.xmit_queue : ''}`}>
                                {q.name} <span className="text-gray-500">{'\u2192'}</span> <span className="text-white">{q.remote_qm}</span>
                              </span>
                            ))}
                            {rq.length > 5 && <span className="text-[9px] text-gray-600">+{rq.length - 5}</span>}
                          </div>
                        )}
                        {aq.length > 0 && (
                          <div className="flex flex-wrap gap-1 items-start">
                            <span className="text-[9px] text-purple-500 font-semibold w-10 shrink-0">ALIAS</span>
                            {aq.slice(0, 5).map((q, i) => (
                              <span key={i} className="font-mono text-[9px] bg-purple-950/40 border border-purple-900/30 px-1 py-0.5 rounded text-purple-300 truncate max-w-[180px]">
                                {q.name}{q.remote_queue ? ` → ${q.remote_queue}` : ''}
                              </span>
                            ))}
                            {aq.length > 5 && <span className="text-[9px] text-gray-600">+{aq.length - 5}</span>}
                          </div>
                        )}
                        {xq.length > 0 && (
                          <div className="flex flex-wrap gap-1 items-start">
                            <span className="text-[9px] text-cyan-500 font-semibold w-10 shrink-0">XMIT</span>
                            {xq.slice(0, 5).map((q, i) => (
                              <span key={i} className="font-mono text-[9px] bg-cyan-950/40 border border-cyan-900/30 px-1 py-0.5 rounded text-cyan-300 truncate max-w-[180px]">{q.name}</span>
                            ))}
                            {xq.length > 5 && <span className="text-[9px] text-gray-600">+{xq.length - 5}</span>}
                          </div>
                        )}
                        {lq.length === 0 && rq.length === 0 && aq.length === 0 && xq.length === 0 && (
                          <span className="text-[9px] text-gray-600">No queues</span>
                        )}
                      </div>
                    </div>
                  );
                })}
                {focusedNode.clients.length > 8 && (
                  <span className="text-[10px] text-gray-600">+{focusedNode.clients.length - 8} more apps</span>
                )}
              </div>
            </div>
          )}

          {/* Channels from/to this node */}
          {focusedEdges.length > 0 && (
            <div className="border-t border-gray-800 pt-2 mt-2">
              <div className="text-[10px] text-gray-500 font-semibold uppercase tracking-wider mb-1">
                Channels ({focusedEdges.length})
              </div>
              <div className="grid gap-0.5 max-h-28 overflow-y-auto">
                {focusedEdges.slice(0, 20).map((e, i) => (
                  <div key={i} className="text-[10px] font-mono flex items-center gap-1.5 flex-wrap">
                    <span className="text-indigo-400">{e.name}</span>
                    <span className="text-gray-600">{e.from} {'\u2192'} {e.to}</span>
                    <span className={`px-1 rounded ${
                      e.topology === 'backbone' ? 'bg-amber-900/50 text-amber-300' :
                      e.topology === 'spoke_to_hub' ? 'bg-emerald-900/50 text-emerald-300' :
                      e.topology === 'hub_to_spoke' ? 'bg-blue-900/50 text-blue-300' :
                      'bg-gray-800 text-gray-400'
                    }`}>{e.topology}</span>
                    {e.flows.length > 0 && <span className="text-gray-600 text-[9px]">{e.flows[0]}{e.flows.length > 1 ? ` +${e.flows.length - 1}` : ''}</span>}
                  </div>
                ))}
                {focusedEdges.length > 20 && <span className="text-[10px] text-gray-600">+{focusedEdges.length - 20} more</span>}
              </div>
            </div>
          )}

          {/* No channels message for isolated nodes */}
          {focusedEdges.length === 0 && focusedNeighbors.length === 0 && (
            <div className="border-t border-gray-800 pt-2 mt-2 text-[10px] text-gray-600">
              No channels — this QM has only local queues (self-contained)
            </div>
          )}

          {/* Aggregate members */}
          {focusedNode.is_aggregate && focusedNode.members?.length > 0 && (
            <div className="border-t border-gray-800 pt-2 mt-2">
              <span className="text-[10px] text-gray-600">Members: </span>
              {focusedNode.members.slice(0, 20).map((m, i) => (
                <span key={m} className="text-[10px] font-mono text-gray-400">{i > 0 ? ', ' : ''}{m}</span>
              ))}
              {focusedNode.members.length > 20 && <span className="text-[10px] text-gray-600"> +{focusedNode.members.length - 20}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

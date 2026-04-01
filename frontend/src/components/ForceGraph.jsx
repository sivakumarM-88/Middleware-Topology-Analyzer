import { useRef, useEffect, useState, useMemo } from 'react';
import * as d3 from 'd3';

const COMMUNITY_COLORS = [
  '#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#14b8a6', '#f97316', '#06b6d4', '#84cc16',
];

const COMMUNITY_COLORS_DIM = [
  '#6366f133', '#10b98133', '#f59e0b33', '#ef444433', '#8b5cf633',
  '#ec489933', '#14b8a633', '#f9731633', '#06b6d433', '#84cc1633',
];

// Above this many nodes, aggregate into community summary nodes
const MAX_DIRECT_NODES = 300;

/**
 * Aggregate large graphs by community: each community becomes one summary node.
 * Hub nodes and unclustered nodes stay as-is.
 */
function aggregateGraph(data) {
  if (!data || data.nodes.length <= MAX_DIRECT_NODES) return data;

  const communityMap = {};  // community_id → { nodes, clients, ports, ... }
  const standalone = [];     // nodes without community

  for (const n of data.nodes) {
    const cid = n.community_id;
    if (cid == null) {
      standalone.push(n);
      continue;
    }
    if (!communityMap[cid]) {
      communityMap[cid] = { id: `community_${cid}`, nodes: [], clients: 0, ports: 0, hubs: [] };
    }
    const cm = communityMap[cid];
    cm.nodes.push(n.id);
    cm.clients += n.client_count || 0;
    cm.ports += n.port_count || 0;
    if (n.is_hub) cm.hubs.push(n.id);
  }

  // Build aggregated nodes
  const aggNodes = [];

  // Keep standalone nodes
  for (const n of standalone) {
    aggNodes.push(n);
  }

  // One node per community
  const nodeToAgg = {};  // original node id → aggregated node id
  for (const [cid, cm] of Object.entries(communityMap)) {
    const hubLabel = cm.hubs.length > 0 ? ` (Hub: ${cm.hubs[0]})` : '';
    const aggNode = {
      id: cm.id,
      name: `Community ${cid}${hubLabel}`,
      type: 'queue_manager',
      region: '',
      community_id: parseInt(cid),
      is_hub: cm.hubs.length > 0,
      client_count: cm.clients,
      clients: [{ id: cm.id, app_id: `${cm.nodes.length} QMs`, name: `${cm.clients} apps`, role: 'both' }],
      port_count: cm.ports,
      local_queues: 0,
      remote_queues: 0,
      alias_queues: 0,
    };
    aggNodes.push(aggNode);
    for (const nid of cm.nodes) {
      nodeToAgg[nid] = cm.id;
    }
  }

  // Build aggregated links (deduplicate after mapping)
  const seenLinks = new Set();
  const aggLinks = [];
  for (const l of data.links) {
    const src = nodeToAgg[l.source] || l.source;
    const tgt = nodeToAgg[l.target] || l.target;
    if (src === tgt) continue;
    const key = `${src}->${tgt}`;
    if (seenLinks.has(key)) continue;
    seenLinks.add(key);
    aggLinks.push({ ...l, id: key, source: src, target: tgt, name: key });
  }

  return {
    nodes: aggNodes,
    links: aggLinks,
    summary: {
      ...data.summary,
      aggregated: true,
      original_nodes: data.nodes.length,
      original_edges: data.links.length,
      total_nodes: aggNodes.length,
      total_edges: aggLinks.length,
    },
  };
}


export default function ForceGraph({ data, width = 600, height = 500, title = '', onSelectNode }) {
  const svgRef = useRef();
  const [selectedNode, setSelectedNode] = useState(null);

  // Aggregate if too many nodes
  const graphData = useMemo(() => aggregateGraph(data), [data]);

  useEffect(() => {
    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    const defs = svg.append('defs');
    const g = svg.append('g');

    // Zoom
    const zoom = d3.zoom()
      .scaleExtent([0.2, 5])
      .on('zoom', (event) => g.attr('transform', event.transform));
    svg.call(zoom);

    // Clone data to avoid d3 mutation issues
    const nodes = graphData.nodes.map((d) => ({ ...d }));
    const links = graphData.links.map((d) => ({ ...d }));

    // Build node lookup map for O(1) access (instead of nodes.find per link)
    const nodeMap = new Map(nodes.map((n) => [n.id, n]));

    // Node size based on app count + queues
    const nodeRadius = (d) => {
      const base = d.is_hub ? 45 : 32;
      const extra = Math.min((d.client_count || 0) * 3, 15);
      return base + extra;
    };

    // Tune force params for graph size
    const n = nodes.length;
    const chargeStrength = n > 100 ? -400 : -800;
    const linkDist = n > 100 ? 150 : 220;

    const simulation = d3
      .forceSimulation(nodes)
      .force('link', d3.forceLink(links).id((d) => d.id).distance(linkDist).strength(0.5))
      .force('charge', d3.forceManyBody().strength(chargeStrength).distanceMax(500))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius((d) => nodeRadius(d) + 20))
      .force('x', d3.forceX(width / 2).strength(0.05))
      .force('y', d3.forceY(height / 2).strength(0.05))
      .alphaDecay(n > 100 ? 0.05 : 0.0228);  // Settle faster for large graphs

    // Arrow markers - one per community color
    COMMUNITY_COLORS.forEach((color, i) => {
      defs.append('marker')
        .attr('id', `arrow-${i}`)
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 10)
        .attr('refY', 0)
        .attr('markerWidth', 8)
        .attr('markerHeight', 8)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L10,0L0,4')
        .attr('fill', color)
        .attr('opacity', 0.6);
    });
    // Default arrow
    defs.append('marker')
      .attr('id', 'arrow-default')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 10)
      .attr('refY', 0)
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-4L10,0L0,4')
      .attr('fill', '#4b5563')
      .attr('opacity', 0.6);

    // Glow filter for hubs
    const filter = defs.append('filter').attr('id', 'glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur');
    const feMerge = filter.append('feMerge');
    feMerge.append('feMergeNode').attr('in', 'coloredBlur');
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // --- LINKS (curved paths) ---
    const linkGroup = g.append('g').attr('class', 'links');

    const linkPath = linkGroup
      .selectAll('path')
      .data(links)
      .enter()
      .append('path')
      .attr('fill', 'none')
      .attr('stroke', (d) => {
        const srcNode = nodeMap.get(d.source.id || d.source);
        if (srcNode && srcNode.community_id != null) {
          return COMMUNITY_COLORS[srcNode.community_id % COMMUNITY_COLORS.length];
        }
        return '#4b5563';
      })
      .attr('stroke-width', (d) => d.topology === 'backbone' ? 3 : 1.5)
      .attr('stroke-dasharray', (d) => d.topology === 'backbone' ? '8,4' : 'none')
      .attr('stroke-opacity', 0.4)
      .attr('marker-end', (d) => {
        const srcNode = nodeMap.get(d.source.id || d.source);
        if (srcNode && srcNode.community_id != null) {
          return `url(#arrow-${srcNode.community_id % COMMUNITY_COLORS.length})`;
        }
        return 'url(#arrow-default)';
      });

    // Channel name label on links (skip for large graphs — too cluttered)
    let linkLabel;
    if (n <= 50) {
      linkLabel = linkGroup
        .selectAll('text')
        .data(links)
        .enter()
        .append('text')
        .attr('font-size', 8)
        .attr('fill', '#6b7280')
        .attr('text-anchor', 'middle')
        .attr('dy', -6)
        .text((d) => d.name || '');
    }

    // --- NODES ---
    const nodeGroup = g.append('g').attr('class', 'nodes');

    const node = nodeGroup
      .selectAll('g')
      .data(nodes)
      .enter()
      .append('g')
      .attr('cursor', 'pointer')
      .call(
        d3.drag()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Click handler
    node.on('click', (event, d) => {
      event.stopPropagation();
      setSelectedNode((prev) => prev?.id === d.id ? null : d);
      if (onSelectNode) onSelectNode(d);
    });

    // Hub outer glow ring
    node
      .filter((d) => d.is_hub)
      .append('circle')
      .attr('r', (d) => nodeRadius(d) + 6)
      .attr('fill', 'none')
      .attr('stroke', '#fbbf24')
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', '4,3')
      .attr('opacity', 0.5)
      .attr('filter', 'url(#glow)');

    // Main node rectangle (rounded rect for a "card" look)
    node.each(function (d) {
      const el = d3.select(this);
      const r = nodeRadius(d);
      const color = COMMUNITY_COLORS[(d.community_id ?? 0) % COMMUNITY_COLORS.length];
      const colorDim = COMMUNITY_COLORS_DIM[(d.community_id ?? 0) % COMMUNITY_COLORS.length];

      // Background circle
      el.append('circle')
        .attr('r', r)
        .attr('fill', colorDim)
        .attr('stroke', color)
        .attr('stroke-width', d.is_hub ? 3 : 1.5);

      // QM name (large, centered)
      el.append('text')
        .text(d.id.length > 16 ? d.id.slice(0, 14) + '..' : d.id)
        .attr('text-anchor', 'middle')
        .attr('dy', d.client_count > 0 ? -8 : 2)
        .attr('font-size', d.is_hub ? 13 : 11)
        .attr('font-weight', 700)
        .attr('font-family', 'monospace')
        .attr('fill', '#f3f4f6');

      // App list inside node (limit display for large graphs)
      const clients = d.clients || [];
      if (clients.length > 0 && clients.length <= 4) {
        clients.forEach((c, i) => {
          el.append('text')
            .text(`${c.app_id} (${c.role[0].toUpperCase()})`)
            .attr('text-anchor', 'middle')
            .attr('dy', 6 + i * 12)
            .attr('font-size', 8)
            .attr('fill', '#9ca3af')
            .attr('font-family', 'monospace');
        });
      } else if (clients.length > 4) {
        el.append('text')
          .text(`${clients.length} apps`)
          .attr('text-anchor', 'middle')
          .attr('dy', 8)
          .attr('font-size', 9)
          .attr('fill', '#9ca3af');
      }

      // Queue count badge (bottom)
      const queueCount = d.port_count || 0;
      if (queueCount > 0) {
        const badgeY = r - 4;
        el.append('circle')
          .attr('cx', r * 0.6)
          .attr('cy', -badgeY + 10)
          .attr('r', 10)
          .attr('fill', '#1f2937')
          .attr('stroke', '#4b5563')
          .attr('stroke-width', 1);
        el.append('text')
          .text(queueCount)
          .attr('x', r * 0.6)
          .attr('y', -badgeY + 10)
          .attr('text-anchor', 'middle')
          .attr('dy', 3.5)
          .attr('font-size', 8)
          .attr('font-weight', 600)
          .attr('fill', '#d1d5db');
      }

      // Hub badge
      if (d.is_hub) {
        el.append('text')
          .text('HUB')
          .attr('text-anchor', 'middle')
          .attr('dy', -r - 8)
          .attr('font-size', 9)
          .attr('font-weight', 700)
          .attr('fill', '#fbbf24')
          .attr('letter-spacing', '1px');
      }

      // Community label
      if (d.community_id != null) {
        el.append('text')
          .text(`C${d.community_id}`)
          .attr('text-anchor', 'middle')
          .attr('dy', r + 14)
          .attr('font-size', 8)
          .attr('fill', '#6b7280');
      }
    });

    // Background click clears selection
    svg.on('click', () => setSelectedNode(null));

    // --- TICK ---
    simulation.on('tick', () => {
      // Curved links
      linkPath.attr('d', (d) => {
        const dx = d.target.x - d.source.x;
        const dy = d.target.y - d.source.y;
        const dr = Math.sqrt(dx * dx + dy * dy) * 0.8;
        // Shorten path to stop at node edge
        const srcR = nodeRadius(d.source);
        const tgtR = nodeRadius(d.target);
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const sx = d.source.x + (dx * srcR) / dist;
        const sy = d.source.y + (dy * srcR) / dist;
        const tx = d.target.x - (dx * tgtR) / dist;
        const ty = d.target.y - (dy * tgtR) / dist;
        return `M${sx},${sy}A${dr},${dr} 0 0,1 ${tx},${ty}`;
      });

      if (linkLabel) {
        linkLabel
          .attr('x', (d) => (d.source.x + d.target.x) / 2)
          .attr('y', (d) => (d.source.y + d.target.y) / 2);
      }

      node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    // Initial zoom to fit
    simulation.on('end', () => {
      const bounds = g.node().getBBox();
      if (bounds.width === 0) return;
      const pad = 40;
      const fullWidth = bounds.width + pad * 2;
      const fullHeight = bounds.height + pad * 2;
      const scale = Math.min(width / fullWidth, height / fullHeight, 1.2);
      const tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
      const ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
      svg.transition().duration(500).call(
        zoom.transform,
        d3.zoomIdentity.translate(tx, ty).scale(scale)
      );
    });

    return () => simulation.stop();
  }, [graphData, width, height]);

  const isAggregated = graphData?.summary?.aggregated;

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl overflow-hidden">
      {title && (
        <div className="px-4 py-2 border-b border-gray-800 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-300">{title}</span>
          <span className="text-xs text-gray-500">
            {isAggregated ? (
              <>
                {graphData.summary.original_nodes} QMs aggregated into {graphData.summary.total_nodes} groups &middot; {graphData.summary.total_edges} channels
              </>
            ) : graphData?.summary ? (
              <>
                {graphData.summary.total_nodes} QMs &middot; {graphData.summary.total_edges} channels &middot; {graphData.summary.total_clients} apps
              </>
            ) : null}
          </span>
        </div>
      )}
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="w-full bg-gray-950/50"
        viewBox={`0 0 ${width} ${height}`}
      />
      {/* Selected node detail panel */}
      {selectedNode && (
        <div className="px-4 py-3 border-t border-gray-800 bg-gray-900/80 text-xs">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono font-bold text-white text-sm">{selectedNode.id}</span>
            {selectedNode.is_hub && <span className="text-amber-400 font-semibold">HUB</span>}
            {selectedNode.community_id != null && (
              <span className="px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">Community {selectedNode.community_id}</span>
            )}
            {selectedNode.region && <span className="text-gray-500">{selectedNode.region}</span>}
          </div>
          <div className="grid grid-cols-3 gap-3 text-gray-400 mb-2">
            <div>Apps: <span className="text-white">{selectedNode.client_count}</span></div>
            <div>Queues: <span className="text-white">{selectedNode.port_count}</span></div>
            <div>
              L:{selectedNode.local_queues || 0} R:{selectedNode.remote_queues || 0} A:{selectedNode.alias_queues || 0}
            </div>
          </div>
          {selectedNode.clients && selectedNode.clients.length > 0 && selectedNode.clients.length <= 20 && (
            <div className="space-y-1">
              {selectedNode.clients.map((c) => (
                <div key={c.id} className="flex items-center gap-2">
                  <span className="font-mono text-indigo-400">{c.app_id}</span>
                  <span className="text-gray-500">{c.name}</span>
                  <span className={`px-1 rounded text-[10px] ${
                    c.role === 'producer' ? 'bg-emerald-900/50 text-emerald-400' :
                    c.role === 'consumer' ? 'bg-amber-900/50 text-amber-400' :
                    'bg-purple-900/50 text-purple-400'
                  }`}>{c.role}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

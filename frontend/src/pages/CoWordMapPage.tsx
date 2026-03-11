import { useEffect, useState, useRef, useCallback } from "react";
import ForceGraph2D, { ForceGraphMethods, NodeObject, LinkObject } from "react-force-graph-2d";
import { getCoWordNetwork, CoWordNetworkData } from "../api";

interface GraphNode extends NodeObject {
  id: string;
  label: string;
  size: number;
  frequency: number;
  cluster: string;
  color: string;
}

interface GraphLink extends LinkObject {
  source: string;
  target: string;
  weight: number;
  width: number;
}

export default function CoWordMapPage() {
  const [data, setData] = useState<CoWordNetworkData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [minFrequency, setMinFrequency] = useState(50);
  const [maxNodes, setMaxNodes] = useState(150);
  const [selectedCluster, setSelectedCluster] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink> | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({ width: rect.width, height: window.innerHeight - 56 });
      }
    };
    updateDimensions();
    window.addEventListener("resize", updateDimensions);
    return () => window.removeEventListener("resize", updateDimensions);
  }, []);

  useEffect(() => { loadData(); }, [minFrequency, maxNodes]);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const result = await getCoWordNetwork(minFrequency, maxNodes);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load network data");
    } finally {
      setLoading(false);
    }
  }

  const filteredData = useCallback(() => {
    if (!data) return { nodes: [], links: [] };
    let nodes = data.nodes as GraphNode[];
    let edges = data.edges;
    if (selectedCluster) {
      const nodeIds = new Set(nodes.filter(n => n.cluster === selectedCluster).map(n => n.id));
      nodes = nodes.filter(n => nodeIds.has(n.id));
      edges = edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    }
    return { nodes, links: edges.map(e => ({ source: e.source, target: e.target, weight: e.weight, width: e.width })) };
  }, [data, selectedCluster]);

  const paintNode = useCallback((node: GraphNode, ctx: CanvasRenderingContext2D) => {
    const size = node.size || 5;
    const isHovered = hoveredNode?.id === node.id;
    const nodeRadius = isHovered ? size * 1.5 : size;
    ctx.beginPath();
    ctx.arc(node.x || 0, node.y || 0, nodeRadius, 0, 2 * Math.PI);
    ctx.fillStyle = node.color || "#666";
    ctx.fill();
    ctx.strokeStyle = isHovered ? "#fff" : "rgba(0, 0, 0, 0.5)";
    ctx.lineWidth = isHovered ? 3 : Math.max(1.5, size / 10);
    ctx.stroke();
    if (size > 12 || isHovered) {
      ctx.font = `${isHovered ? "bold " : ""}${Math.max(8, size / 2)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#fff";
      ctx.fillText(node.label, node.x || 0, (node.y || 0) + nodeRadius + 8);
    }
  }, [hoveredNode]);

  const graphData = filteredData();

  return (
    <div className="fixed inset-0 left-56 flex flex-col bg-gray-950">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-700">
        <div className="flex items-center gap-6">
          <h1 className="text-xl font-bold">Co-Word Network Map</h1>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <label className="text-gray-400">Min Freq:</label>
              <input type="range" min="10" max="500" step="10" value={minFrequency} onChange={(e) => setMinFrequency(Number(e.target.value))} className="w-20" />
              <span className="text-white w-10">{minFrequency}</span>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-gray-400">Max Nodes:</label>
              <input type="range" min="50" max="300" step="10" value={maxNodes} onChange={(e) => setMaxNodes(Number(e.target.value))} className="w-20" />
              <span className="text-white w-10">{maxNodes}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {data && (
            <div className="flex gap-3 text-xs text-gray-400">
              <span>Nodes: <b className="text-white">{graphData.nodes.length}</b></span>
              <span>Edges: <b className="text-white">{graphData.links.length}</b></span>
            </div>
          )}
          <button onClick={loadData} disabled={loading} className="px-3 py-1.5 bg-violet-600 hover:bg-violet-500 rounded text-sm disabled:opacity-50">
            {loading ? "..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Graph container - full screen */}
      <div ref={containerRef} className="flex-1 relative">
        {error && <div className="absolute top-4 left-4 right-4 bg-red-900/80 border border-red-700 rounded-lg p-3 text-red-400 text-sm z-10">{error}</div>}
        
        {loading ? (
          <div className="h-full flex items-center justify-center text-gray-400">
            <div className="text-center">
              <div className="animate-spin h-8 w-8 border-2 border-violet-500 border-t-transparent rounded-full mx-auto mb-2" />
              Loading network data...
            </div>
          </div>
        ) : data && graphData.nodes.length > 0 ? (
          <ForceGraph2D
            ref={graphRef}
            width={dimensions.width}
            height={dimensions.height}
            graphData={graphData}
            nodeId="id"
            nodeLabel={(node: GraphNode) => `${node.label}\nFrequency: ${node.frequency.toLocaleString()}\nCluster: ${node.cluster.replace(/_/g, " ")}`}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node: GraphNode, color, ctx) => { ctx.beginPath(); ctx.arc(node.x || 0, node.y || 0, (node.size || 5) * 1.5, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill(); }}
            linkColor={() => "rgba(255,255,255,0.12)"}
            linkWidth={(link: GraphLink) => link.width || 1}
            linkDirectionalParticles={0}
            onNodeHover={(node) => setHoveredNode(node as GraphNode | null)}
            onNodeClick={(node: GraphNode) => { graphRef.current?.centerAt(node.x, node.y, 500); graphRef.current?.zoom(2, 500); }}
            cooldownTicks={100}
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
            backgroundColor="transparent"
          />
        ) : (
          <div className="h-full flex items-center justify-center text-gray-500">{data?.nodes.length === 0 ? "No nodes match the current filter" : "No data available"}</div>
        )}

        {/* Floating cluster legend - bottom center toast */}
        {data && data.clusters.length > 0 && (
          <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 bg-gray-900/95 backdrop-blur-sm border border-gray-700 rounded-xl px-4 py-3 shadow-2xl z-20 max-w-4xl">
            <div className="flex flex-wrap items-center justify-center gap-2">
              <button 
                onClick={() => setSelectedCluster(null)} 
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${selectedCluster === null ? "bg-white text-gray-900 shadow-lg" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white"}`}
              >
                All ({data.nodes.length})
              </button>
              {data.clusters.map((cluster) => (
                <button
                  key={cluster.id}
                  onClick={() => setSelectedCluster(selectedCluster === cluster.id ? null : cluster.id)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all flex items-center gap-1.5 ${selectedCluster === cluster.id ? "bg-white text-gray-900 shadow-lg" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-white"}`}
                >
                  <span className="w-2.5 h-2.5 rounded-full border border-black/20" style={{ backgroundColor: cluster.color }} />
                  {cluster.label}
                  <span className="text-gray-500 ml-0.5">{cluster.nodeCount}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Hovered node info - appears above cluster legend */}
        {hoveredNode && (
          <div className="absolute bottom-24 left-1/2 transform -translate-x-1/2 bg-gray-800/95 border border-gray-600 rounded-lg px-4 py-2 shadow-xl z-30">
            <div className="flex items-center gap-3">
              <span className="w-4 h-4 rounded-full border border-black/30" style={{ backgroundColor: hoveredNode.color }} />
              <span className="font-bold">{hoveredNode.label}</span>
              <span className="text-gray-500">|</span>
              <span className="text-sm text-gray-400">Freq: <b className="text-white">{hoveredNode.frequency.toLocaleString()}</b></span>
              <span className="text-gray-500">|</span>
              <span className="text-sm text-gray-400"><b className="text-white">{hoveredNode.cluster.replace(/_/g, " ")}</b></span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

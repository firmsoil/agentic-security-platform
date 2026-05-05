"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";

import type { AttackPath, AttackPathEdge, AttackPathNode, Ontology } from "../lib/api";

type GraphClientProps = {
  ontology: Ontology;
  attackPaths: AttackPath[];
};

const CATEGORY_COLORS: Record<string, { fill: string; border: string }> = {
  ai: { fill: "rgba(208, 188, 255, 0.15)", border: "#d0bcff" }, // Purple
  identity: { fill: "rgba(255, 180, 169, 0.15)", border: "#ffb4ab" }, // Orange/Coral
  data: { fill: "rgba(242, 184, 181, 0.15)", border: "#f2b8b5" }, // Error/Red
  code: { fill: "rgba(168, 199, 250, 0.15)", border: "#a8c7fa" }, // Primary Blue
  infrastructure: { fill: "rgba(128, 216, 207, 0.15)", border: "#80d8cf" }, // Teal
  security: { fill: "rgba(253, 198, 151, 0.15)", border: "#fdc697" }, // Orange/Yellow
  event: { fill: "rgba(196, 199, 197, 0.15)", border: "#c4c7c5" }, // Neutral
};

export function GraphClient({ ontology, attackPaths }: GraphClientProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [selectedPathId, setSelectedPathId] = useState<string | null>(attackPaths[0]?.id ?? null);

  const selectedPath = useMemo(
    () => attackPaths.find((path) => path.id === selectedPathId) ?? attackPaths[0] ?? null,
    [attackPaths, selectedPathId],
  );

  const nodeCategoryByType = useMemo(() => {
    const mapping = new Map<string, string>();
    for (const node of ontology.nodes) {
      mapping.set(node.name, node.category);
    }
    return mapping;
  }, [ontology.nodes]);

  const graphData = useMemo(() => {
    const nodeMap = new Map<string, AttackPathNode>();
    const edgeMap = new Map<string, AttackPathEdge>();
    for (const path of attackPaths) {
      for (const node of path.graph_nodes) {
        nodeMap.set(node.id, node);
      }
      for (const edge of path.graph_edges) {
        edgeMap.set(edge.id, edge);
      }
    }
    const highlightedNodeIds = new Set(selectedPath?.graph_nodes.map((node) => node.id) ?? []);
    const highlightedEdgeIds = new Set(selectedPath?.graph_edges.map((edge) => edge.id) ?? []);
    const elements = [
      ...[...nodeMap.values()].map((node) => ({
        data: {
          id: node.id,
          label: node.name,
          nodeType: node.node_type,
          category: nodeCategoryByType.get(node.node_type) ?? node.category,
          highlighted: highlightedNodeIds.has(node.id) ? "true" : "false",
        },
      })),
      ...[...edgeMap.values()].map((edge) => ({
        data: {
          id: edge.id,
          source: edge.source_id,
          target: edge.target_id,
          label: edge.edge_type,
          edgeType: edge.edge_type,
          highlighted: highlightedEdgeIds.has(edge.id) ? "true" : "false",
        },
      })),
    ];
    return {
      nodes: [...nodeMap.values()],
      edges: [...edgeMap.values()],
      elements,
    };
  }, [attackPaths, nodeCategoryByType, selectedPath]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const cy = cytoscape({
      container: containerRef.current,
      elements: graphData.elements,
      layout: {
        name: "breadthfirst",
        directed: true,
        padding: 40,
        spacingFactor: 1.25,
      },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "text-valign": "bottom",
            "text-halign": "center",
            "text-margin-y": 8,
            "font-size": "12px",
            "font-family": "system-ui, -apple-system, sans-serif",
            "font-weight": 500,
            color: "#e3e3e3",
            width: 44,
            height: 44,
            shape: "ellipse",
            "border-width": 2,
            "background-color": "#2b2d30",
            "border-color": "#747775",
          },
        },
        ...Object.entries(CATEGORY_COLORS).map(([category, colors]) => ({
          selector: `node[category = "${category}"]`,
          style: {
            "background-color": colors.fill,
            "border-color": colors.border,
            "border-width": 2,
          },
        })),
        {
          selector: 'node[highlighted = "false"]',
          style: {
            opacity: 0.4,
          },
        },
        {
          selector: 'node[highlighted = "true"]',
          style: {
            opacity: 1,
            "border-width": 3,
            "border-color": "#a8c7fa",
            "underlay-color": "#a8c7fa",
            "underlay-padding": 8,
            "underlay-opacity": 0.2,
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            label: "",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "arrow-scale": 1.2,
            "line-color": "#444746",
            "target-arrow-color": "#444746",
            opacity: 0.4,
          },
        },
        {
          selector: 'edge[highlighted = "true"]',
          style: {
            width: 2.5,
            opacity: 1,
            "line-color": "#a8c7fa",
            "target-arrow-color": "#a8c7fa",
          },
        },
      ],
    });
    cy.fit(undefined, 40);
    return () => {
      cy.destroy();
    };
  }, [graphData.elements]);

  const legendEntries = useMemo(() => {
    const categories = [...new Set(ontology.nodes.map((node) => node.category))];
    return categories.map((category) => ({
      category,
      colors: CATEGORY_COLORS[category] ?? CATEGORY_COLORS.event,
    }));
  }, [ontology.nodes]);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 380px",
        gap: 24,
        alignItems: "start",
      }}
    >
      <section
        style={{
          border: "1px solid #333639",
          borderRadius: 16,
          background: "#1e1f20",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid #333639",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            flexWrap: "wrap",
            background: "#282a2c",
          }}
        >
          <div>
            <div style={{ fontSize: 16, fontWeight: 500, color: "#e3e3e3" }}>Security Topology</div>
            <div style={{ marginTop: 4, color: "#c4c7c5", fontSize: 13 }}>
              {graphData.nodes.length} nodes · {graphData.edges.length} connections · {attackPaths.length} threat vectors
            </div>
          </div>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {legendEntries.map((entry) => (
              <div
                key={entry.category}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "#c4c7c5", fontSize: 12, textTransform: "capitalize" }}
              >
                <span
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: "50%",
                    display: "inline-block",
                    background: entry.colors.fill,
                    border: `2px solid ${entry.colors.border}`,
                  }}
                />
                {entry.category}
              </div>
            ))}
          </div>
        </div>
        <div
          ref={containerRef}
          style={{
            height: "70vh",
            minHeight: 600,
            background: "#131314",
          }}
        />
      </section>

      <aside
        style={{
          display: "grid",
          gap: 24,
          alignContent: "start",
          height: "70vh",
          minHeight: 600,
          overflowY: "auto",
          paddingRight: 8,
        }}
      >
        <section
          style={{
            border: "1px solid #333639",
            borderRadius: 16,
            background: "#1e1f20",
            padding: 24,
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 500, color: "#e3e3e3", marginBottom: 16 }}>Detected Vectors</div>
          <div style={{ display: "grid", gap: 12 }}>
            {attackPaths.length === 0 ? (
              <div style={{ color: "#c4c7c5", fontSize: 14 }}>
                No threat vectors identified in current scan.
              </div>
            ) : (
              attackPaths.map((path) => {
                const selected = path.id === selectedPath?.id;
                return (
                  <button
                    key={path.id}
                    type="button"
                    onClick={() => setSelectedPathId(path.id)}
                    style={{
                      textAlign: "left",
                      borderRadius: 12,
                      border: selected ? "1px solid #a8c7fa" : "1px solid #444746",
                      background: selected ? "rgba(168, 199, 250, 0.08)" : "transparent",
                      padding: "16px",
                      color: "#e3e3e3",
                      cursor: "pointer",
                      transition: "all 0.2s ease",
                      position: "relative",
                      overflow: "hidden",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start" }}>
                      <span style={{ fontWeight: 500, fontSize: 14, lineHeight: 1.4, color: selected ? "#a8c7fa" : "#e3e3e3" }}>{path.title}</span>
                      <div
                        style={{
                          background: "#8c1d18",
                          color: "#f2b8b5",
                          padding: "2px 8px",
                          borderRadius: 12,
                          fontSize: 12,
                          fontWeight: 600,
                        }}
                      >
                        {path.score.toFixed(1)}
                      </div>
                    </div>
                    <div style={{ marginTop: 8, color: "#c4c7c5", fontSize: 12, textTransform: "capitalize" }}>
                      {path.kind.replaceAll("_", " ")} · {path.length} hops
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        <section
          style={{
            border: "1px solid #333639",
            borderRadius: 16,
            background: "#1e1f20",
            padding: 24,
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 500, color: "#e3e3e3", marginBottom: 20 }}>Vector Details</div>
          {selectedPath ? (
            <div style={{ display: "grid", gap: 24 }}>
              <div>
                <div style={{ color: "#a8c7fa", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Narrative</div>
                <div style={{ marginTop: 8, fontSize: 14, lineHeight: 1.5, color: "#e3e3e3" }}>{selectedPath.title}</div>
              </div>

              <div>
                <div style={{ color: "#a8c7fa", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Findings</div>
                <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
                  {selectedPath.findings.map((finding) => (
                    <div
                      key={finding}
                      style={{
                        background: "rgba(242, 184, 181, 0.08)",
                        borderLeft: "3px solid #f2b8b5",
                        padding: "10px 14px",
                        borderRadius: "0 8px 8px 0",
                        color: "#e3e3e3",
                        fontSize: 13,
                        lineHeight: 1.5,
                      }}
                    >
                      {finding}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <div style={{ color: "#a8c7fa", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Framework Mappings</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
                  {selectedPath.mappings
                    .filter((mapping) => mapping.framework === "OWASP_AGENTIC_TOP_10_2026")
                    .map((mapping) => (
                      <a
                        key={`${selectedPath.id}-${mapping.framework}-${mapping.identifier}`}
                        href={mapping.url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          textDecoration: "none",
                          border: "1px solid #444746",
                          borderRadius: 16,
                          background: "#2b2d30",
                          color: "#c4c7c5",
                          padding: "6px 12px",
                          fontSize: 12,
                          fontWeight: 500,
                          transition: "all 0.2s ease",
                        }}
                      >
                        {mapping.identifier}
                      </a>
                    ))}
                </div>
              </div>

              <div>
                <div style={{ color: "#a8c7fa", fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px" }}>Execution Path</div>
                <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
                  {selectedPath.graph_nodes.map((node, index) => {
                    const category = nodeCategoryByType.get(node.node_type) ?? node.category;
                    const colors = CATEGORY_COLORS[category] ?? CATEGORY_COLORS.event;
                    return (
                      <div
                        key={`${selectedPath.id}-${index}-${node.id}`}
                        style={{
                          display: "flex",
                          gap: 16,
                          alignItems: "flex-start",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            width: 24,
                            height: 24,
                            borderRadius: "50%",
                            background: "#2b2d30",
                            color: "#c4c7c5",
                            fontSize: 11,
                            fontWeight: 600,
                            flexShrink: 0,
                            border: "1px solid #444746",
                          }}
                        >
                          {index + 1}
                        </div>
                        <div style={{ flex: 1, paddingBottom: 12, borderBottom: index === selectedPath.graph_nodes.length - 1 ? "none" : "1px solid #333639" }}>
                          <div style={{ fontWeight: 500, fontSize: 14, color: "#e3e3e3" }}>{node.name}</div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                            <span style={{ color: colors.border, fontSize: 12, textTransform: "capitalize" }}>{category}</span>
                            <span style={{ color: "#747775" }}>·</span>
                            <span style={{ color: "#c4c7c5", fontSize: 12 }}>{node.node_type}</span>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: "#c4c7c5", fontSize: 14 }}>
              Select a vector to view details.
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}

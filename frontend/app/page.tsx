import Link from "next/link";

import {
  countAgenticMappedPaths,
  fetchAttackPaths,
  fetchHealth,
  summarizeAgenticMappings,
} from "./lib/api";

function metricCard(label: string, value: string, tone: "red" | "purple" | "blue") {
  const tones = {
    red: { border: "#7f1d1d", value: "#fca5a5", glow: "rgba(220, 38, 38, 0.18)" },
    purple: { border: "#5b21b6", value: "#c4b5fd", glow: "rgba(124, 58, 237, 0.18)" },
    blue: { border: "#1d4ed8", value: "#93c5fd", glow: "rgba(37, 99, 235, 0.18)" },
  } as const;
  const palette = tones[tone];
  return (
    <div
      style={{
        border: `1px solid ${palette.border}`,
        background: palette.glow,
        borderRadius: 8,
        padding: 18,
        minHeight: 116,
      }}
    >
      <div style={{ color: "#9ca3af", fontSize: 12, textTransform: "uppercase" }}>{label}</div>
      <div style={{ marginTop: 10, fontSize: 34, fontWeight: 700, color: palette.value }}>{value}</div>
    </div>
  );
}

export default async function Home() {
  const [health, attackPaths] = await Promise.all([fetchHealth(), fetchAttackPaths()]);
  const mappedCount = countAgenticMappedPaths(attackPaths);
  const topMappings = summarizeAgenticMappings(attackPaths);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0f0f0f",
        color: "#e3e3e3",
      }}
    >
      <div
        style={{
          maxWidth: 1600,
          margin: "0 auto",
          padding: "24px",
        }}
      >
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            marginBottom: 32,
            flexWrap: "wrap",
            paddingBottom: 24,
            borderBottom: "1px solid #333639",
          }}
        >
          <div>
            <div style={{ color: "#a8c7fa", fontSize: 13, textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 600 }}>
              Platform Overview
            </div>
            <h2 style={{ margin: "8px 0 6px", fontSize: 28, fontWeight: 400, color: "#f8f9fa", letterSpacing: "-0.5px" }}>
              Agentic Security Platform
            </h2>
            <div style={{ color: "#c4c7c5", fontSize: 15 }}>
              Graph-native, telemetry-driven, agentic security for AI-native applications.
            </div>
          </div>
        </header>
        <section
          style={{
            display: "grid",
            gap: 28,
            gridTemplateColumns: "minmax(0, 1.3fr) minmax(320px, 0.7fr)",
            alignItems: "stretch",
          }}
        >
          <div>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                border: "1px solid #233042",
                borderRadius: 999,
                padding: "8px 12px",
                color: "#93c5fd",
                fontSize: 13,
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 999,
                  background: health ? "#22c55e" : "#ef4444",
                  display: "inline-block",
                }}
              />
              {health ? `API ${health.status} · ${health.version}` : "API unreachable"}
            </div>
            <h1
              style={{
                margin: "20px 0 12px",
                fontSize: 56,
                lineHeight: 1.02,
                maxWidth: 760,
              }}
            >
              ASP found {attackPaths.length} attack path{attackPaths.length === 1 ? "" : "s"} in your environment.
            </h1>
            <p
              style={{
                margin: 0,
                maxWidth: 760,
                color: "#9ca3af",
                fontSize: 18,
                lineHeight: 1.6,
              }}
            >
              {mappedCount} of them map directly to the OWASP Agentic Top 10. This demo pivots from
              graph-native AI inventory to exploitability, so the story lands in one screen instead
              of five dashboards.
            </p>
            <div style={{ display: "flex", gap: 14, marginTop: 28, flexWrap: "wrap" }}>
              <Link
                href="/graph"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 148,
                  height: 46,
                  padding: "0 18px",
                  borderRadius: 8,
                  background: "#2563eb",
                  color: "#eff6ff",
                  textDecoration: "none",
                  fontWeight: 600,
                }}
              >
                View graph
              </Link>
              <a
                href="#overview"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  minWidth: 148,
                  height: 46,
                  padding: "0 18px",
                  borderRadius: 8,
                  border: "1px solid #334155",
                  color: "#d1d5db",
                  textDecoration: "none",
                  fontWeight: 600,
                }}
              >
                Review findings
              </a>
            </div>
          </div>

          <div
            style={{
              border: "1px solid #1f2937",
              borderRadius: 8,
              padding: 24,
              background: "rgba(15, 23, 42, 0.72)",
            }}
          >
            <div style={{ color: "#9ca3af", fontSize: 13, textTransform: "uppercase" }}>
              Agentic coverage
            </div>
            <div
              style={{
                marginTop: 16,
                display: "grid",
                gap: 14,
              }}
            >
              {(topMappings.length > 0 ? topMappings : ["Seed the demo graph to populate OWASP mappings."]).map((item) => (
                <div
                  key={item}
                  style={{
                    borderLeft: "3px solid #ef4444",
                    paddingLeft: 12,
                    color: "#e5e7eb",
                    lineHeight: 1.5,
                  }}
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section
          id="overview"
          style={{
            marginTop: 32,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 16,
          }}
        >
          {metricCard("Attack paths", String(attackPaths.length), "red")}
          {metricCard("OWASP Agentic mapped", String(mappedCount), "purple")}
          {metricCard(
            "Highest score",
            attackPaths.length > 0 ? attackPaths[0].score.toFixed(1) : "0.0",
            "blue",
          )}
        </section>

        <section
          style={{
            marginTop: 24,
            display: "grid",
            gap: 16,
            gridTemplateColumns: "minmax(0, 1fr) minmax(300px, 360px)",
          }}
        >
          <div
            style={{
              border: "1px solid #1f2937",
              borderRadius: 8,
              background: "rgba(9, 12, 18, 0.88)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "16px 18px",
                borderBottom: "1px solid #1f2937",
                display: "flex",
                justifyContent: "space-between",
                gap: 16,
                alignItems: "center",
              }}
            >
              <div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>Live attack-path queue</div>
                <div style={{ marginTop: 4, color: "#9ca3af", fontSize: 14 }}>
                  Ranked by exploitability and mapped at query time.
                </div>
              </div>
              <Link href="/graph" style={{ color: "#93c5fd", textDecoration: "none", fontWeight: 600 }}>
                Open graph
              </Link>
            </div>
            <div style={{ display: "grid" }}>
              {attackPaths.length === 0 ? (
                <div style={{ padding: 24, color: "#9ca3af" }}>
                  No materialized attack paths yet. Seed Neo4j with the vulnerable demo app to see
                  the graph light up.
                </div>
              ) : (
                attackPaths.map((path) => (
                  <div
                    key={path.id}
                    style={{
                      padding: 18,
                      borderTop: "1px solid #111827",
                      display: "grid",
                      gap: 10,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 16 }}>
                      <div>
                        <div style={{ fontWeight: 600 }}>{path.title}</div>
                        <div style={{ marginTop: 4, color: "#9ca3af", fontSize: 14 }}>
                          {path.nodes.join(" → ")}
                        </div>
                      </div>
                      <div style={{ color: "#fca5a5", fontWeight: 700 }}>{path.score.toFixed(1)}</div>
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {path.mappings
                        .filter((mapping) => mapping.framework === "OWASP_AGENTIC_TOP_10_2026")
                        .map((mapping) => (
                          <span
                            key={`${path.id}-${mapping.identifier}`}
                            style={{
                              border: "1px solid #7f1d1d",
                              background: "rgba(127, 29, 29, 0.18)",
                              color: "#fecaca",
                              borderRadius: 999,
                              padding: "4px 10px",
                              fontSize: 12,
                            }}
                          >
                            {mapping.identifier}
                          </span>
                        ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div
            style={{
              border: "1px solid #1f2937",
              borderRadius: 8,
              padding: 20,
              background: "rgba(15, 23, 42, 0.72)",
            }}
          >
            <ul style={{ margin: "0", paddingLeft: 18, color: "#d1d5db", lineHeight: 1.8 }}>
              <li>Prompt injection, tool abuse, and memory poisoning path families</li>
              <li>OWASP Agentic Top 10 mappings resolved from ontology metadata</li>
              <li>Regulated-data sink highlighted directly in the graph</li>
            </ul>
          </div>
        </section>
      </div>
    </main>
  );
}

import Link from "next/link";

import { fetchAttackPaths, fetchOntology } from "../lib/api";
import { GraphClient } from "./graph-client";

export default async function GraphPage() {
  const [ontology, attackPaths] = await Promise.all([fetchOntology(), fetchAttackPaths()]);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "#0f0f0f",
        color: "#e3e3e3",
      }}
    >
      <div style={{ maxWidth: 1600, margin: "0 auto", padding: "24px" }}>
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 16,
            marginBottom: 24,
            flexWrap: "wrap",
            paddingBottom: 24,
            borderBottom: "1px solid #333639",
          }}
        >
          <div>
            <div style={{ color: "#a8c7fa", fontSize: 13, textTransform: "uppercase", letterSpacing: "0.5px", fontWeight: 600 }}>
              Security Posture
            </div>
            <h1 style={{ margin: "8px 0 6px", fontSize: 28, fontWeight: 400, color: "#f8f9fa", letterSpacing: "-0.5px" }}>
              Attack-Path Explorer
            </h1>
            <div style={{ color: "#c4c7c5", fontSize: 15 }}>
              Interactive ontology-driven view of identified security risks.
            </div>
          </div>
          <Link
            href="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              height: 40,
              padding: "0 24px",
              borderRadius: 20,
              border: "1px solid #747775",
              color: "#e3e3e3",
              textDecoration: "none",
              fontWeight: 500,
              fontSize: 14,
            }}
          >
            Overview
          </Link>
        </header>

        {ontology ? (
          <GraphClient ontology={ontology} attackPaths={attackPaths} />
        ) : (
          <div
            style={{
              border: "1px solid #333639",
              borderRadius: 12,
              padding: 32,
              color: "#c4c7c5",
              background: "#1e1f20",
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 18, marginBottom: 8, color: "#f8f9fa" }}>Ontology Data Unavailable</div>
            <div>The graph view requires `/api/ontology` and `/api/security/attack-paths` to be reachable.</div>
          </div>
        )}
      </div>
    </main>
  );
}

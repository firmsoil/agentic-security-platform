export type HealthStatus = {
  status: string;
  version: string;
};

export type OntologyNode = {
  name: string;
  category: string;
  description: string;
};

export type OntologyEdge = {
  name: string;
  category: string;
  description: string;
};

export type Ontology = {
  version: string;
  nodes: OntologyNode[];
  edges: OntologyEdge[];
};

export type FrameworkMapping = {
  framework: string;
  identifier: string;
  title?: string | null;
  url?: string | null;
};

export type AttackPathNode = {
  id: string;
  tenant_id: string;
  node_type: string;
  category: string;
  name: string;
  properties: Record<string, unknown>;
};

export type AttackPathEdge = {
  id: string;
  tenant_id: string;
  edge_type: string;
  source_id: string;
  target_id: string;
  properties: Record<string, unknown>;
};

export type AttackPath = {
  id: string;
  tenant_id: string;
  kind: string;
  title: string;
  score: number;
  length: number;
  nodes: string[];
  findings: string[];
  first_seen?: string | null;
  mappings: FrameworkMapping[];
  graph_nodes: AttackPathNode[];
  graph_edges: AttackPathEdge[];
};

function getBaseUrl(): string {
  return process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

async function fetchJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${getBaseUrl()}${path}`, { cache: "no-store" });
    if (!res.ok) {
      return null;
    }
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchHealth(): Promise<HealthStatus | null> {
  return fetchJson<HealthStatus>("/health");
}

export async function fetchOntology(): Promise<Ontology | null> {
  return fetchJson<Ontology>("/api/ontology");
}

export async function fetchAttackPaths(): Promise<AttackPath[]> {
  return (await fetchJson<AttackPath[]>("/api/security/attack-paths")) ?? [];
}

export function countAgenticMappedPaths(paths: AttackPath[]): number {
  return paths.filter((path) =>
    path.mappings.some((mapping) => mapping.framework === "OWASP_AGENTIC_TOP_10_2026"),
  ).length;
}

export function summarizeAgenticMappings(paths: AttackPath[]): string[] {
  const counts = new Map<string, number>();
  for (const path of paths) {
    for (const mapping of path.mappings) {
      if (mapping.framework !== "OWASP_AGENTIC_TOP_10_2026") {
        continue;
      }
      const label = mapping.title ? `${mapping.identifier} ${mapping.title}` : mapping.identifier;
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, 4)
    .map(([label, count]) => `${label} (${count})`);
}

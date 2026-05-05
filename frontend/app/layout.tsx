import type { ReactNode } from "react";

export const metadata = {
  title: "Agentic Security Platform",
  description: "Graph-native, agentic security for AI-native applications",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          fontFamily:
            "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          background: "#0f0f0f",
          color: "#e3e3e3",
        }}
      >
        {children}
      </body>
    </html>
  );
}

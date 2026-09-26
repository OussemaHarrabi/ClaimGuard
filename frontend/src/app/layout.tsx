import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "ClaimGuard · Review workspace",
  description: "Evidence-first review for deterministic claim checks.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

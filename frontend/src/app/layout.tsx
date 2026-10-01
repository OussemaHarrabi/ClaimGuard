import type { Metadata } from "next";

import "./globals.css";
import "./product.css";

export const metadata: Metadata = {
  title: "ClaimGuard · Clarity before every claim",
  description: "Bring claim checks, evidence, AI guidance, and your review team into one accountable workflow.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

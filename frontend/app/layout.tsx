import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Content Intelligence",
  description: "Know what to create next. Before you create it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

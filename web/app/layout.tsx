import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Network Growth Agent",
  description: "Source-backed networking and personal-brand workflows.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Network Growth Agent",
  description: "Source-backed networking and personal-brand workflows.",
};

const navigation = [
  ["Overview", "/"],
  ["Signals", "/signals"],
  ["Opportunities", "/opportunities"],
  ["Content Studio", "/studio"],
] as const;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <aside className="sidebar">
            <Link href="/" className="brand">
              <span className="brandMark">N</span>
              <span>Network Growth</span>
            </Link>
            <nav aria-label="Primary navigation">
              {navigation.map(([label, href]) => (
                <Link key={href} href={href}>{label}</Link>
              ))}
            </nav>
            <div className="safetyNote">Human approval stays between every draft and external action.</div>
          </aside>
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}

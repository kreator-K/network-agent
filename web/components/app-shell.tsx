import Link from "next/link";
import { logout } from "@/app/login/actions";

const navigation = [["Overview", "/"], ["Signals", "/signals"], ["Opportunities", "/opportunities"], ["Content Studio", "/studio"]] as const;

export function AppShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="shell"><aside className="sidebar"><Link href="/" className="brand"><span className="brandMark">N</span><span>Network Growth</span></Link><nav aria-label="Primary navigation">{navigation.map(([label, href]) => <Link key={href} href={href}>{label}</Link>)}</nav><div className="safetyNote">Human approval stays between every draft and external action.</div><form action={logout}><button className="logout" type="submit">Sign out</button></form></aside><main>{children}</main></div>;
}

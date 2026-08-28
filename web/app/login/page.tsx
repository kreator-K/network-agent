import { login } from "./actions";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <main className="loginPage"><section className="loginCard"><span className="brandMark">N</span><p className="eyebrow">Private workspace</p><h1>Welcome back.</h1><p>Enter the owner password to open Network Growth Agent.</p><form action={login}><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" required />{error ? <div className="formError" role="alert">That password was not accepted.</div> : null}<button type="submit">Open workspace</button></form></section></main>;
}

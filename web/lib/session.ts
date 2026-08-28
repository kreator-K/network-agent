import "server-only";

import { createHmac, scryptSync, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const COOKIE_NAME = "network_owner_session";
const SESSION_SECONDS = 60 * 60 * 8;

function secret(): string | null {
  const value = process.env.WEB_SESSION_SECRET;
  return value && value.length >= 32 ? value : null;
}

function signature(expires: number, key: string): string {
  return createHmac("sha256", key).update(`owner:${expires}`).digest("hex");
}

export async function hasValidSession(): Promise<boolean> {
  const key = secret();
  const token = (await cookies()).get(COOKIE_NAME)?.value;
  if (!key || !token) return false;
  const [expiresText, supplied] = token.split(".");
  const expires = Number(expiresText);
  if (!Number.isSafeInteger(expires) || expires <= Math.floor(Date.now() / 1000) || !supplied) return false;
  const expected = signature(expires, key);
  const left = Buffer.from(supplied, "hex");
  const right = Buffer.from(expected, "hex");
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function requireSession(): Promise<void> {
  if (!(await hasValidSession())) redirect("/login");
}

export async function createSession(): Promise<void> {
  const key = secret();
  if (!key) throw new Error("Web session authentication is not configured.");
  const expires = Math.floor(Date.now() / 1000) + SESSION_SECONDS;
  (await cookies()).set(COOKIE_NAME, `${expires}.${signature(expires, key)}`, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: SESSION_SECONDS,
  });
}

export async function destroySession(): Promise<void> {
  (await cookies()).delete(COOKIE_NAME);
}

export function verifyOwnerPassword(password: string): boolean {
  const stored = process.env.WEB_OWNER_PASSWORD_HASH || "";
  const [salt, expectedHex] = stored.split(":");
  if (!salt || !expectedHex || password.length > 256) return false;
  const actual = scryptSync(password, salt, 64);
  const expected = Buffer.from(expectedHex, "hex");
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

"use server";

import { redirect } from "next/navigation";
import { createSession, destroySession, verifyOwnerPassword } from "@/lib/session";

export async function login(formData: FormData) {
  const password = String(formData.get("password") || "");
  if (!verifyOwnerPassword(password)) redirect("/login?error=invalid");
  await createSession();
  redirect("/");
}

export async function logout() {
  await destroySession();
  redirect("/login");
}

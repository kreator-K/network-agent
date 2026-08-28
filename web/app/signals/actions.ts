"use server";

import { revalidatePath } from "next/cache";
import { scanSignals } from "@/lib/api";
import { requireSession } from "@/lib/session";

export async function runSignalScan() {
  await requireSession();
  await scanSignals();
  revalidatePath("/signals");
  revalidatePath("/");
}

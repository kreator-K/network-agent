import { readFileSync } from "node:fs";
import { randomBytes, scryptSync } from "node:crypto";

const password = process.argv[2] || readFileSync(0, "utf8").trim();
if (!password || password.length < 12) {
  throw new Error("Pass a password of at least 12 characters via an argument or standard input.");
}
const salt = randomBytes(16).toString("hex");
process.stdout.write(`${salt}:${scryptSync(password, salt, 64).toString("hex")}\n`);

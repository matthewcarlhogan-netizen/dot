import { NextResponse } from "next/server";

const API_URL = process.env.MORPHANUS_API_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  let inference = { status: "unreachable", backend: "unknown", device: "unknown" };
  let accounts = { totalKeys: 0, activeKeys: 0 };

  try {
    const res = await fetch(`${API_URL}/api/v1/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      const data = await res.json();
      inference = data.inference ?? inference;
      accounts = data.accounts ?? accounts;
    }
  } catch {}

  return NextResponse.json({
    ok: true,
    product: "morphanus-web",
    mode: "production",
    commerceEnabled: true,
    inference,
    accounts,
  });
}

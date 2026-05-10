import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    ok: true,
    product: "morphanus-web",
    mode: "web-mvp",
    commerceEnabled: false,
    inference: {
      status: "stub",
      replacementTarget: "hosted-gpu-api",
    },
  });
}

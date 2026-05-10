import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

function jsonError(message: string, status = 400) {
  return NextResponse.json({ ok: false, error: message }, { status });
}

export async function POST(request: NextRequest) {
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (contentLength > MAX_UPLOAD_BYTES) {
    return jsonError("Upload is over the 25MB web MVP limit.", 413);
  }

  const form = await request.formData();
  const consent = form.get("consent");
  const source = form.get("source");
  const frame = form.get("frame");

  if (consent !== "true") {
    return jsonError("Consent is required before creating an export.");
  }

  if (!(source instanceof File) || source.size === 0) {
    return jsonError("Upload a source image or short video first.");
  }

  if (!(frame instanceof File) || frame.size === 0) {
    return jsonError("Start the camera and capture a preview frame first.");
  }

  const jobId = `mw_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;

  return NextResponse.json({
    ok: true,
    jobId,
    status: "complete",
    billing: {
      creditsConsumed: 0,
      reason: "Commerce is locked until commercial rights and hosted inference are cleared.",
    },
    limits: {
      maxOutput: "720p",
      mode: "short-export",
    },
    inference: {
      mode: "stub",
      nextBackend: "hosted-gpu-api",
    },
  });
}

import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const API_URL = process.env.MORPHANUS_API_URL ?? "http://127.0.0.1:8000";
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
  const apiKey = (form.get("api_key") as string | null) ?? request.headers.get("x-api-key") ?? "";

  if (consent !== "true") {
    return jsonError("Consent is required before creating an export.");
  }
  if (!(source instanceof File) || source.size === 0) {
    return jsonError("Upload a source image first.");
  }
  if (!source.type.startsWith("image/")) {
    return jsonError("This export path supports image sources only.", 415);
  }
  if (!(frame instanceof File) || frame.size === 0) {
    return jsonError("Start the camera and capture a preview frame first.");
  }
  if (!apiKey) {
    return jsonError("API key is required. Enter your key to continue.", 402);
  }

  const apiForm = new FormData();
  apiForm.append("source", source);
  apiForm.append("target", frame, "camera-frame.png");
  apiForm.append("api_key", apiKey);

  let apiResponse: Response;
  try {
    apiResponse = await fetch(`${API_URL}/api/v1/swap`, {
      method: "POST",
      body: apiForm,
    });
  } catch {
    return jsonError("The swap service is not running. Start it with: python api_server.py", 503);
  }

  if (!apiResponse.ok) {
    const text = await apiResponse.text();
    try {
      const data = JSON.parse(text);
      return NextResponse.json(
        { ok: false, error: data.detail ?? text },
        { status: apiResponse.status }
      );
    } catch {
      return NextResponse.json({ ok: false, error: text }, { status: apiResponse.status });
    }
  }

  const imageBuffer = Buffer.from(await apiResponse.arrayBuffer());
  const jobId = apiResponse.headers.get("x-job-id") ?? "unknown";
  const creditsConsumed = apiResponse.headers.get("x-credits-consumed") ?? "1";
  const creditsRemaining = apiResponse.headers.get("x-credits-remaining") ?? "0";

  return new NextResponse(imageBuffer, {
    status: 200,
    headers: {
      "Content-Type": "image/png",
      "X-Job-Id": jobId,
      "X-Credits-Consumed": creditsConsumed,
      "X-Credits-Remaining": creditsRemaining,
    },
  });
}

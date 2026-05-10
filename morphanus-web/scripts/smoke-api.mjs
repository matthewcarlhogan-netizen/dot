const baseUrl = process.env.MORPHANUS_WEB_URL ?? "http://127.0.0.1:3000";

async function assertResponse(name, response, expectedStatus) {
  const text = await response.text();
  if (response.status !== expectedStatus) {
    throw new Error(`${name} returned ${response.status}, expected ${expectedStatus}: ${text}`);
  }
  const data = JSON.parse(text);
  if (data.ok !== (expectedStatus < 400)) {
    throw new Error(`${name} returned inconsistent ok flag: ${text}`);
  }
  return data;
}

const health = await assertResponse("health", await fetch(`${baseUrl}/api/health`), 200);
if (health.commerceEnabled !== false || health.inference?.status !== "stub") {
  throw new Error(`health route should keep commerce locked and inference stubbed: ${JSON.stringify(health)}`);
}

const sample = new File([new Uint8Array([1, 2, 3, 4])], "sample.png", { type: "image/png" });

const missingConsent = new FormData();
missingConsent.append("consent", "false");
missingConsent.append("source", sample);
missingConsent.append("frame", sample);
await assertResponse("missing consent", await fetch(`${baseUrl}/api/export`, { method: "POST", body: missingConsent }), 400);

const validExport = new FormData();
validExport.append("consent", "true");
validExport.append("source", sample);
validExport.append("frame", sample);
const exportResult = await assertResponse("valid export", await fetch(`${baseUrl}/api/export`, { method: "POST", body: validExport }), 200);
if (exportResult.billing?.creditsConsumed !== 0 || exportResult.inference?.mode !== "stub") {
  throw new Error(`export route should not consume credits in MVP mode: ${JSON.stringify(exportResult)}`);
}

console.log(`Morphanus Web smoke passed at ${baseUrl}`);

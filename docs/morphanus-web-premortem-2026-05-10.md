# Morphanus Web Premortem - 2026-05-10

## Current State

Morphanus Web now has a browser-first MVP shell in `morphanus-web/`. It supports source upload, browser camera capture, consent gating, browser-side source compositing into the captured camera frame, a short-export API contract, and a zero-credit stub export.

The Python DOT app remains a prototype and model lab. It is not the customer-facing universal product.

## Failure Story If This Still Fails

The product fails if the remote demo is treated as the finished product. The web shell proves the right distribution direction, but the business is still blocked by hosted inference, commercial model rights, metering, abuse controls, and account/payment infrastructure.

## Highest-Risk Gaps

- Commercial rights are unresolved for model code and weights.
- `/api/export` is still a stub, not hosted GPU inference.
- There is no account system, payment, credit ledger, or retry-safe billing.
- There is no abuse-reporting or identity/consent enforcement beyond the MVP checkbox.
- Temporary tunnels are not production hosting.
- Uploaded demo media reaches the local Mac through the tunnel; the demo should not be used for sensitive media.

## Optimization Done

- Moved the customer path to a zero-install Next web app.
- Locked commerce and credits until rights and metering are real.
- Added a browser-side demo composite so the uploaded source appears in the exported camera frame.
- Added source type and size validation on client and API.
- Added clearer camera unsupported/permission errors.
- Added `npm run smoke` to verify health, consent rejection, and zero-credit export behavior.
- Added a remote demo note in Notion and a local runtime PID/URL record under `.morphanus-runtime/`.

## Next Optimization

- Replace the export stub with a real hosted inference worker contract.
- Add a durable job store with `queued`, `processing`, `complete`, and `failed` states.
- Add upload retention limits and deletion policy before real users upload media.
- Add account and credits only after exports are reliable and rights are cleared.
- Replace localtunnel with stable hosting before sharing outside internal testing.

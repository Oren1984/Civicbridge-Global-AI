# Integration capability matrix

No CivicBridge adapter talks to a real government system. Adapters exist so that the workflow, retries and failure handling are real and the contracts are ready to replace. Code: `backend/app/services/integrations.py`, registry table `integration_adapters`, runs in `integration_runs`.

| Adapter code | Name | State | Jurisdiction | Capabilities | What actually happens |
|---|---|---|---|---|---|
| `de-ber-registration-mock` | Berlin registration gateway (mock) | mock | DE-BE-BER | submit_request, status_ack | In-process synthetic gateway returns a `SIM-ACK-…` acknowledgement recorded on the case timeline |
| `il-population-mock` | Population services exchange (mock) | mock | IL | submit_request, status_ack | Same, for the Israeli demo authority |
| `us-sf-services-mock` | City services gateway (mock) | mock | US-CA-SF | submit_request, status_ack | Same, for the San Francisco demo authority |
| `de-pension-liaison-mock` | Pension liaison exchange (mock) | mock | DE | evidence_exchange | Registered with the same in-process mock behaviour; the consent handoff itself does not depend on it |
| `il-tlv-sandbox` | Municipal reports sandbox | sandbox | IL-TA-TLV | submit_request | Real HTTP round-trip to the local sandbox endpoint `/api/integrations/sandbox/echo` (internal only) |
| `reference-packs-public` | Reference source snapshot | public_data | — | read_reference_sources | Reads the bundled source snapshot |

States: `mock` (synthetic in-process), `public_data` (bundled public reference snapshot), `sandbox` (real HTTP to a local sandbox), `authorized_live` (defined in the model; **no adapter in this installation**).

## Contract

Every call is a job with an idempotency key, a timeout (`timeout_ms`), bounded retries with back-off (`max_retries`), a dead-letter state, recorded errors and a timeline event on the case. Results are labelled "simulated exchange; not an official government submission" in the UI.

## Testing failure handling

Governance › Integrations lets an administrator inject `timeout` or `error` per adapter. The resulting retries and the dead-lettered job are visible in Governance › Jobs, where they can be re-queued. Backend evidence: `tests/test_sync_meetings_ops.py` (dead letter and retry).

## Replacing an adapter with a real system

A real adapter would need, at minimum: a legal basis and agreement with the authority, its authentication scheme, a data-protection assessment, mapping of the request payload, and a new state `authorized_live` set only after review. None of this exists here.

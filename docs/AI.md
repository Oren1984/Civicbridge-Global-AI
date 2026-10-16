# AI, retrieval and tool boundaries

AI in CivicBridge assists people; it never decides. Code: `backend/app/ai/`, `backend/app/routers/{ai,rights,translations}.py`.

## Modes (policy `ai_mode`, default `mock`)

| Mode | Behaviour | Verified |
|---|---|---|
| `rules` | Deterministic rules and templates only. No generated text; translation opens a manual workspace. | yes (backend tests) |
| `mock` | Deterministic, labelled fixture outputs. No model, no downloads, no keys. | yes (backend tests, browser journeys) |
| `ollama` | Local model via the optional `ollama` profile. Answers must cite retrieved passages, otherwise the extractive answer is returned; translations get number/date preservation checks. | **no** |

The current mode is shown in AI outputs ("Mode: …") and in Governance › AI oversight.

## Rights Navigator (rules)

`app/ai/rules.py` evaluates rule versions from the jurisdiction packs: `all`/`any` conditions, detection of missing inputs, citations to source passages, and uncertainty flags (synthetic rule, review date passed, unreviewed, low confidence, placeholder source). Outcomes are phrased as indications (`likely_applicable`, `likely_not_applicable`, `insufficient_information`). Consequential programmes offer a human review that creates a request routed to the responsible authority.

## Retrieval (RAG)

- Embeddings are deterministic lexical hash vectors (`app/ai/embeddings.py`) stored in pgvector with an HNSW index; no semantic model.
- The caller's authorized document IDs are applied **inside the SQL query before scoring**, so unauthorized passages are never ranked.
- An abstention gate requires at least two normalised shared terms plus a similarity floor, or one strong match; otherwise the answer is "no supported answer" with the closest passages listed.
- Warnings for stale or placeholder sources. Text that looks like instructions ("ignore previous…") is flagged and treated as data.

## Tool gateway (`app/ai/tools.py`)

| Tool | Workspaces | Consequential |
|---|---|---|
| `summarize_case` | citizen, authority, institution, professional | no |
| `suggest_next_steps` | citizen, professional | no |
| `draft_message` | citizen, professional, authority | no |
| `send_case_message` | citizen, professional, authority | **yes — needs explicit human approval** |
| `draft_decision_rationale` | authority | no (scaffold only) |

Permanently forbidden, whatever the request: submit an official application, issue or approve a decision, deny eligibility, release personal records, dispatch emergency services, delete records, change a case's state.

Every call passes: allowlist → workspace scope → resource authorization → hourly budget (`ai_budget_per_hour`, 60) → pydantic input validation → wall-clock limit (`ai_tool_timeout_s`, 8 s) → output size check. Every attempt, allowed or denied, is stored in `ai_tool_calls` and audited. The planner for `/api/ai/assist` reads only the user's request, never document text.

## Translation

`mock` translates only phrases from the 10-entry demo glossary (`packs/glossary.json`) and marks every other segment `untranslated`; unsupported content is reported as such. Translations are reviewed and approved by the owner or a delegate with `translation_review`. `is_certified` is always false.

## Oversight

Governance › AI oversight shows calls by tool and status and recent refusals and pending approvals, without inputs or outputs (they may contain personal data).

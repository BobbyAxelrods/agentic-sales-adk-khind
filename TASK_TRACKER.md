# KHIND Sales Agent Task Tracker

Last updated: 2026-09-12

## Completed

- [x] Modular prompt foundation
  - Core prompt, stage fragments, product USPs, and GCS media mapping.
  - State-driven prompt assembler.
- [x] ADK root agent
  - `root_agent` uses Gemini 2.5 Flash and `get_khind_instruction`.
- [x] Session tools
  - Product selection, once-per-product USP tracking, stage advancement.
  - RAG cache invalidates on product changes.
- [x] Vertex RAG tool
  - Async retrieval with a per-session query cache.
- [x] Session-level escalation tool
  - Approved labels: coverage unsupported, no payslip, human request, angry customer, RAG error.
- [x] Product RAG Markdown corpus
  - Eight product-specific Markdown files with stable product keys and aliases.
- [x] Source conversion helper
  - Extracts PDF/TXT source content into Markdown using PyMuPDF.
- [x] Deterministic application-form prompt
  - Uses the complete approved KHIND form and prevents repeated full-form messages.

## Next

- [x] Webhook and session runtime
  - Receive inbound WhatsApp or Chatwoot messages.
  - Deliver the planned GCS media after a first product selection.

## Status

- The FastAPI bootstrap is now importable and includes a live webhook endpoint at `/webhook` plus `/health` liveness checks.
- The runtime keeps a simple in-memory session store for local/dev execution and exposes the product-selection and media-planning hooks expected by the agent flow.
- ADK Web validation passed with `adk web --port 8000 apps`; the `khind_sales_agent` root agent was discovered and started successfully.

## Recently Completed

- [x] WhatsApp product-list handler
  - Builds one interactive catalog/list payload with product categories.
  - Maps valid list-row IDs to known KHIND product keys.
- [x] Application data collection tools
  - Stores submitted form fields without echoing values in tool responses.
  - Reports only completion and missing-field status.
  - Tracks `application_form_sent` to prevent repeat form delivery.
- [x] Removed product-key list from invalid product responses.
- [x] Deterministic media planning
  - Plans up to two images and one video from the mapped GCS folder.
  - Prevents duplicate initial media per product in each session.

## Upcoming

- [ ] Human-handoff delivery
  - Convert session escalation state into a real Chatwoot label, private note, and assignment.
- [ ] Production RAG setup
  - Upload curated Markdown documents to the Vertex corpus.
  - Verify live product, pricing, warranty, eligibility, and coverage retrieval.
- [ ] End-to-end tests
  - Product selection, first USP/media, follow-up RAG, product switching, coverage, payslip branches, form completion, and escalation.

## Important Decisions

- Gemini detects conversational intent; session tools make state changes deterministic.
- The assembler does not detect intent. It selects prompt fragments from session state.
- WhatsApp interactive UI is reserved for product catalog selection only.
- Media URLs and payloads never enter the model context.
- Product USP is delivered once per product; later questions use RAG only.
- The application form must be shown once in its approved format, then only missing fields are requested.

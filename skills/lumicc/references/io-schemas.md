# I/O Schemas

Full I/O contracts for the main `lumicc` skill and each sub-skill's run-result envelope.

## Main `lumicc` input

```json
{
  "user_intent": "string  // free-form user message",
  "store_url": "string?",
  "platform": "shopify | amazon | tiktok-shop | etsy | independent",
  "target_market": "us | eu | uk | sea | global",
  "stage_hint": "0-to-1 | 1-to-10 | 10-to-100 | auto",
  "language": "en | zh",
  "session_id": "string?",
  "memory_path": "string  // default ~/.commerce-os"
}
```

## Main `lumicc` output

```json
{
  "decision": {
    "matched_subskill": "string  // e.g., lumicc-launch",
    "confidence": 0.0,
    "alternative_subskills": ["string"],
    "reason": "string",
    "missing_inputs": ["string"]
  },
  "store_memory_snapshot": {
    "stage": "0-to-1 | 1-to-10 | 10-to-100",
    "active_campaigns": [
      { "id": "uuid", "type": "cold-start | expansion | crisis | voc | watchtower",
        "status": "planned | running | paused | done | cancelled" }
    ],
    "recent_decisions": ["string"]
  },
  "next_action": {
    "type": "execute_subskill | ask_user | install_dependency",
    "payload": {}
  }
}
```

## Universal sub-skill run-result envelope

Every sub-skill writes `~/.commerce-os/runs/<run_id>/result.json` matching:

```json
{
  "run_id": "uuid",
  "skill": "lumicc-launch | lumicc-watch | ...",
  "store_id": "string?",
  "started_at": 1715000000,
  "finished_at": 1715000300,
  "status": "success | partial | failed",
  "deliverables": [
    { "type": "string", "path": "string", "summary": "string" }
  ],
  "decisions_made": [
    { "key": "string", "value": "any", "rationale": "string", "needs_user_confirm": false }
  ],
  "cost": { "tokens": 0, "usd": 0 },
  "next_recommended_skill": "string?"
}
```

## Notification envelope (agent mode)

When a skill writes to `~/.commerce-os/outbox/<uuid>.json`:

```json
{
  "id": "uuid",
  "ts": 1715000000,
  "skill": "string",
  "run_id": "uuid?",
  "channel": "feishu | discord | telegram | slack | email | stdout",
  "target": "group:GROUP_ID | user:USER_ID | chat:CHAT_ID",
  "title": "string",
  "body_md": "string  // markdown",
  "severity": "info | warn | error"
}
```

## Validation

- `scripts/test_smoke.py` asserts every shape above against real script outputs (21/21 pass).
- `scripts/health_check.py` reports which capability slots fill which optional fields.
- Future: drop a `schemas/*.json` directory with JSON Schema documents so external tools can validate without running tests.

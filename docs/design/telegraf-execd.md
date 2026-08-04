# Telegraf `execd` decode processor — wire contract

**Status:** contract pinned; the `decoderd --telegraf` adapter is **built and verified at the Week 2
Mosquitto → Telegraf → Postgres bench, not blind.** Today `decoderd` ships its harness/CLI schema
(below); the execd adapter is a thin envelope over the *same* `decode::*` core.

## Where decode sits

`mqtt_consumer` (WiCAN JSON in) → **decode (`processors.execd` → `decoderd`)** → `outputs.postgresql`.
Native binary → `execd` is the clear fit over Starlark (see [ADR 0001](../adr/0001-collector-choice.md),
[ADR 0002](../adr/0002-rust-decode-rewrite.md)).

## The execd contract (why an adapter is needed)

`processors.execd` runs the binary once as a long-lived subprocess and, per metric, **serializes a
whole metric to stdin and parses a whole metric back from stdout** (one per line, using the configured
`data_format`). A Telegraf metric is a fixed shape — `name` + `tags` + `fields` + `timestamp` — not
arbitrary JSON.

`decoderd`'s current CLI/harness schema is bespoke request/response, which does **not** match:

| | decoderd CLI/harness (today) | Telegraf `execd` metric (`data_format = "json"`) |
|---|---|---|
| **in**  | `{"mode":"06","hex":"4601010c…"}` | `{"name":"obd","tags":{…},"fields":{"mode":"06","hex":"4601010c…"},"timestamp":…}` |
| **out** | one line, **all records nested** in a `records` array | **one metric line per monitor record** (fan-out), tags/timestamp preserved |

Two gaps: the **envelope** (fields nested under a metric with tags + timestamp) and the **fan-out**
(one Mode 06 response decodes to N monitor records → N metrics → N Postgres rows, one per monitor per
timestamp — exactly the time-series shape we want).

## Recommended adapter: `decoderd --telegraf`

Add a `--telegraf` flag (metric-JSON in/out) alongside the default bespoke schema, both dispatching to
the **same** `decode::decode_mode06` / `parse_mode01` core:

- **Default `decoderd`** stays the equivalence-harness target + CLI. The frozen golden corpus and
  `harness/test_equivalence.py` remain about OBD/J1979 truth — Telegraf's envelope never leaks into the
  decode oracle.
- **`decoderd --telegraf`** reads metric-JSON, pulls `fields.mode` / `fields.hex`, decodes, and emits
  one metric line per record — carrying the decoded fields (`test_value`, `min_limit`, `max_limit`,
  `unit`, `passed`, …) with `mid`/`tid`/`uasid` as tags, and the source `tags` + `timestamp` preserved.

This preserves ADR 0002's "**tests exercise the exact deployed artifact**" premise: the tested unit is
the decode core; the adapter is a serialization shell over it.

## Telegraf config sketch (to confirm at the bench)

```toml
[[processors.execd]]
  command = ["decoderd", "--telegraf"]
  data_format = "json"        # confirm JSON vs influx line-protocol against the installed Telegraf
  # json_v2 / field-key options set once the WiCAN payload shape is known
```

**Bench checklist (Week 2):** confirm the exact serializer/parser keys against the installed Telegraf
version; feed synthetic Mode 06 JSON via local Mosquitto; assert one Postgres row per monitor with the
scaled fields; then wire it into the gateway config (Phase 7).

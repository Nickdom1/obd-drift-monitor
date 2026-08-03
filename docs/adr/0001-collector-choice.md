# ADR 0001: Telegraf for MQTT→Postgres Telemetry Pipeline

**Status:** Accepted  
**Date:** 2026-08-02  
**Deciders:** Nick  
**Context:** Week 1, pre-hardware reconnaissance

## Context

The gateway appliance needs a component to consume MQTT messages from the WiCAN Pro (containing raw OBD-II responses as JSON), decode those payloads into structured monitor readings, and write them to PostgreSQL 16 (native range partitioning, no Timescale). This is the core telemetry pipeline.

Two standard tools were evaluated:
1. **OpenTelemetry Collector (otelcol-contrib)**
2. **Telegraf**

The design principle is "configure, don't handroll"—we want declarative config files over custom daemons wherever possible.

## Decision

**Use Telegraf** with the `mqtt_consumer` input plugin, a Starlark or execd processor for decode, and the `postgresql` output plugin.

## Rationale

### Coverage of Both Ends

**Telegraf:**
- ✅ Ships `inputs.mqtt_consumer` with QoS 1, persistent sessions, and delivery-tracking acknowledgments
- ✅ Ships `outputs.postgresql` natively (supports batching, connection pooling, prepared statements)
- ✅ Supports decode-as-processor via Starlark (embedded scripting) or execd (subprocess with JSON I/O)

**OpenTelemetry Collector:**
- ❌ No MQTT receiver in otelcol-contrib as of the week-1 research pass
  - MQTT was proposed in [open-telemetry/opentelemetry-collector-contrib#4629](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/4629) but remains unimplemented
  - Would require a custom receiver or a bridge process (defeats "configure don't code")
- ❌ Postgres exporter exists only as an unimplemented proposal ([#32483](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/32483))
  - Current SQL exporters target ClickHouse, BigQuery, etc.—not Postgres
  - Would require OTLP → another bridge → Postgres (adding latency and failure modes)

### MQTT Consumer Quality

Telegraf's `mqtt_consumer` provides:
- **QoS 1 with persistent sessions:** guarantees at-least-once delivery even across gateway reboots
- **Topic pattern matching:** `/obd/+/mode06` style wildcards for multiple monitors or future multi-vehicle
- **TLS/mutual TLS support:** `ca_cert`, `client_cert`, `client_key` for encrypted WiCAN→gateway link
- **Connection resilience:** automatic reconnection with exponential backoff

These are table-stakes features for a ~10-year appliance; implementing them in a custom bridge would replicate 2000+ lines of battle-tested code.

### Decode Strategy

**Option A (preferred):** Starlark processor
- Telegraf's `processors.starlark` plugin embeds a sandboxed Python-like scripting language
- Decode logic lives in a `.star` file alongside `telegraf.conf`
- No subprocess overhead, no serialization between decode and database write

**Option B (fallback):** Execd processor
- `processors.execd` spawns our Python decode library as a long-running subprocess
- Telegraf sends JSON on stdin, receives transformed JSON on stdout
- Clean separation: decode library has zero Telegraf dependencies, remains pure
- Fallback if Starlark's standard library is too limited (e.g., missing bit-packing utils)

Both options keep the decode table (`decode_table.csv`) and core logic in version control. If decode fights back as a processor, a thin bridge script owning *only* decode remains an acceptable retreat—**documented**, not daemon drift.

### Operational Fit

- **Nix packaging:** `pkgs.telegraf` is in nixpkgs, well-maintained, declarative config via `services.telegraf`
- **Observability:** Telegraf exposes Prometheus metrics on its own pipeline (messages received, decode errors, write latency)
- **Community:** Larger install base for MQTT→SQL than OTel Collector (more Stack Overflow answers for weird edge cases)

## Alternatives Considered

### OpenTelemetry Collector
**Rejected** due to missing MQTT receiver and Postgres exporter. If both were available, OTel's unified observability model (traces/metrics/logs as first-class) would be attractive, but the two-bridge architecture (MQTT bridge → otelcol → Postgres bridge) adds failure modes and latency for no narrative benefit—we're not shipping traces, just structured telemetry.

### Custom Python Daemon
**Rejected** per the core design principle. A 200-line `asyncio` script with `paho-mqtt` and `psycopg3` is easy to write but hard to justify:
- Reinvents connection pooling, reconnection logic, batching, backpressure
- Becomes "Nick's bespoke telemetry daemon" instead of "standard Telegraf config"
- Harder to hand off, harder to debug in production

The point of using Telegraf is that the next person (or Nick in 2030) reads `telegraf.conf` and knows exactly what's running.

### Node-RED
**Rejected.** Visual flow programming is a poor fit for version-controlled infrastructure. Node-RED flows export as opaque JSON blobs; diffs are unreadable. Also adds a Node.js runtime to the gateway for a use case Telegraf already solves.

## Consequences

### Positive
- Single tool covers MQTT consumption, decode (via processor), and Postgres writes
- Declarative config: `telegraf.conf` + optional `.star` or `decode.py` (execd)
- Battle-tested MQTT QoS 1 with persistent sessions
- Gateway config remains a Nix expression, no handrolled daemon

### Negative
- Starlark's standard library may be limiting (fallback: execd subprocess)
- Telegraf's error messages for malformed processor scripts can be cryptic (mitigated: test decode logic standalone via pytest first)
- Adds Telegraf-specific config syntax to learn (but it's well-documented and readable)

### Mitigation
If Starlark proves too limiting or buggy:
1. Switch to execd processor (5-line config change)
2. Run decode library as subprocess—still declarative, still version-controlled, just slightly higher latency
3. ADR this pivot if it happens

## References

- Telegraf MQTT Consumer: [https://github.com/influxdata/telegraf/tree/master/plugins/inputs/mqtt_consumer](https://github.com/influxdata/telegraf/tree/master/plugins/inputs/mqtt_consumer)
- Telegraf PostgreSQL Output: [https://github.com/influxdata/telegraf/tree/master/plugins/outputs/postgresql](https://github.com/influxdata/telegraf/tree/master/plugins/outputs/postgresql)
- Telegraf Starlark Processor: [https://github.com/influxdata/telegraf/tree/master/plugins/processors/starlark](https://github.com/influxdata/telegraf/tree/master/plugins/processors/starlark)
- OTel Collector MQTT Receiver (open issue): [https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/4629](https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/4629)
- Design doc reference: `docs/design/architecture.md` §2 (component decisions)

## Validation

Week 2 (when WiCAN arrives): bench test with local Mosquitto broker publishing synthetic Mode 06 JSON → Telegraf → Postgres. If decode-as-processor causes pain, document the execd pivot and move on.
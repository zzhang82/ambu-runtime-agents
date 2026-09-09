# ADR 0002: Quota Watcher ownership and occurrence lifecycle

Status: Pilot

## Decision

The first Agent Fabric vertical loop is a deterministic, read-only quota watcher
that executes locally in the WSL `runtime-agents` process. It reuses the existing
cron matching and quota/model collector. It does not invoke an LLM, enqueue a
general agent task, write AMB, or mirror the run into PostgreSQL.

Ownership is deliberately small:

* `agentctl` is the task, policy, schedule, and operator interface. It owns when
  a schedule is created and the policy for retry/terminal completion.
* `agentd` is only the existing scheduling invocation loop. It must not become a
  second policy owner. This pilot does not start it.
* Hostkeeper is the Mac execution adapter. It is not involved in this WSL-local
  watcher.
* PostgreSQL remains the existing cross-host coordination authority for work
  that is explicitly dispatched across hosts. This watcher does not duplicate a
  local observation in PostgreSQL.
* The JSONL local queue is scoped to local execution. It is not another owner
  of a task already dispatched to PostgreSQL; this watcher bypasses that queue
  and records its own bounded local evidence.

Schedule creation and worker polling are separate: an operator or `agentctl`
creates the schedule; a bounded foreground watcher reads the schedule and uses
the existing `schedule_due` function to decide whether an occurrence is due.

## Identifier mapping

The watcher uses existing schedule vocabulary and adds only deterministic local
identifiers:

| Concept | Value/format | Ownership |
| --- | --- | --- |
| workflow identity | `quota-watcher` | watcher contract |
| schedule identity | existing `schedule_id` from `schedules.jsonl` | `agentctl` |
| scheduled occurrence | `<schedule_id>:<due_window>` | schedule projection |
| logical run | `quota-watcher:<occurrence_id>` | stable across retry |
| attempt | `attempt-<UUID>` | new for each execution attempt |
| observation | `observation-<UUID>` | one collector result |
| result/evidence reference | relative path under watcher evidence root | watcher evidence |

Retries retain the occurrence and logical run identifiers but always create a
new attempt identifier. The watcher owns retry disposition for this local
workflow and writes a terminal receipt for every attempted occurrence.

## Evidence boundary

Evidence is private JSON under the explicitly supplied pilot state directory.
Only sanitized model IDs, source identities, timestamps, normalized quota state,
and error classes are retained. Credentials, authorization headers, raw provider
responses, account labels, and tokens are never persisted.

`unknown`, `exhausted`, `cached`, and `fresh` remain distinct states. An
unchanged normalized state suppresses a repeated change event, but never
suppresses the occurrence or attempt receipt.

This ADR does not claim NAS durability, cross-host failover, exactly-once
external effects, or a portable worker contract.

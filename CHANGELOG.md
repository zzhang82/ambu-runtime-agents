# Changelog

## 1.2.0

- Extracted internal control model modules (`paths`, `state`, `models`, `policy`, `schedules`, `plans`, `assistant_router`).
- Refactored CLI to delegate to extracted internals while preserving command behavior.
- Added focused unit tests for extracted modules and maintained full CLI acceptance checks.

## 1.1.1

- Initial repo-backed packaging of the existing live runtime-agents install.
- Added editable install support.
- Added smoke checks and regression harness scaffolding.

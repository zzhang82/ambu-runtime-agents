---
id: retry_schedule
title: Retry schedule
risk: read_only
requires_confirmation: false
description: Retry the latest failed schedule.
phrases:
  - retry schedule {schedule}
  - retry {schedule}
inputs:
  schedule:
    type: schedule
    required: true
actions:
  - type: retry_schedule
    schedule: "{schedule}"
response:
  matched: "Retrying schedule {schedule}."
---

Retry a schedule.

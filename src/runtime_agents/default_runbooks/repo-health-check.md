---
id: repo_health_check
title: Repo health check
risk: read_only
requires_confirmation: false
description: Run a read-only workspace health check.
phrases:
  - repo health {workspace}
  - repo health
  - health {workspace}
  - check repo health {workspace}
  - check repo health
inputs:
  workspace:
    type: workspace
    required: true
actions:
  - type: submit_iterate
    workspace: "{workspace}"
    agent: planner
    goal: "Check repo health. Analyze failures only. Do not edit files."
    check: "pytest -q"
    max_rounds: 1
response:
  matched: "I’ll run a read-only health check for {workspace}."
  queued: "Queued repo health check for {workspace}."
---

Run a read-only repo health check.

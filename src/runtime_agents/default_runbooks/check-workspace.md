---
id: check_workspace
title: Check workspace
risk: read_only
requires_confirmation: false
description: Inspect a workspace without editing files.
phrases:
  - check {workspace}
  - inspect {workspace}
  - check workspace {workspace}
  - what is going on in {workspace}
inputs:
  workspace:
    type: workspace
    required: true
actions:
  - type: submit_run
    workspace: "{workspace}"
    agent: planner
    goal: "Inspect workspace {workspace}. Summarize current status, important files, pending issues, and next recommended action. Do not edit files."
response:
  matched: "I’ll inspect workspace {workspace} without editing files."
  queued: "Queued workspace inspection for {workspace}."
---

Inspect a workspace safely.

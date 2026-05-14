---
id: fix_tests
title: Fix failing tests
risk: workspace_write
requires_confirmation: true
description: Create a plan to fix failing tests in a workspace.
phrases:
  - fix tests in {workspace}
  - fix failing tests in {workspace}
  - make tests pass in {workspace}
inputs:
  workspace:
    type: workspace
    required: true
actions:
  - type: create_plan
    workspace: "{workspace}"
    goal: "Fix failing tests in {workspace}. Start with diagnosis. Create bounded subtasks with checks. Do not push or deploy."
response:
  matched: "This may edit workspace files, so I’ll create a plan first."
  confirm: "Reply YES to create a repair plan for {workspace}."
---

Create a bounded repair plan for test failures.

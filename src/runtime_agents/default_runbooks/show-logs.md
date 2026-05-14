---
id: show_logs
title: Show logs
risk: read_only
requires_confirmation: false
description: Show logs for a task.
phrases:
  - show logs {task_id}
  - logs {task_id}
  - show logs
  - logs
inputs:
  task_id:
    type: task_id
    required: true
actions:
  - type: show_logs
    task_id: "{task_id}"
response:
  matched: "Showing logs for task {task_id}."
---

Show task logs.

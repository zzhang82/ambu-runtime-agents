---
id: show_plan
title: Show plan
risk: read_only
requires_confirmation: false
description: Show plan status.
phrases:
  - show plan {plan_id}
  - plan {plan_id}
inputs:
  plan_id:
    type: plan_id
    required: true
actions:
  - type: show_plan
    plan_id: "{plan_id}"
response:
  matched: "Showing plan {plan_id}."
---

Show plan status.

---
id: repair_plan
title: Repair plan
risk: read_only
requires_confirmation: false
description: Generate repair guidance for a blocked plan.
phrases:
  - repair plan {plan_id}
  - repair {plan_id}
  - repair plan
  - what is blocked
inputs:
  plan_id:
    type: plan_id
    required: true
actions:
  - type: repair_plan
    plan_id: "{plan_id}"
response:
  matched: "Preparing repair guidance for plan {plan_id}."
---

Repair a blocked plan.

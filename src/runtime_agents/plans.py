def derive_plan_status(plan, queue_item_for_subtask, latest_plan_event):
    rows = []
    any_failed = False
    any_running = False
    blocked_on = None
    blocked_reason = None
    all_completed = bool(plan.get("subtasks"))
    previous_failed_blocker = None
    previous_open_blocker = None

    for subtask in plan.get("subtasks") or []:
        sid = subtask.get("id")
        item = queue_item_for_subtask(plan.get("plan_id"), sid)
        skip_event = latest_plan_event(plan.get("plan_id"), sid, "skip")
        status = "pending"
        queue_id_value = None
        task_id_value = None
        reason = None

        if skip_event:
            status = "skipped"
            reason = skip_event.get("reason")
        elif previous_failed_blocker:
            status = "blocked"
            reason = "dependency_failed"
        elif previous_open_blocker:
            status = "blocked"
            reason = "dependency_not_completed"
        elif item:
            queue_id_value = item.get("queue_id")
            task_id_value = item.get("task_id")
            qstatus = item.get("status")
            if qstatus == "queued":
                status = "queued"
            elif qstatus == "running":
                status = "running"
            elif qstatus == "completed":
                status = "completed"
            elif qstatus == "approval_required":
                status = "blocked"
                reason = "approval_required"
            elif qstatus == "failed":
                status = "failed"
                reason = "failed"
            elif qstatus == "retrying":
                status = "running"
            elif qstatus == "cancelled":
                status = "blocked"
                reason = "cancelled"

        if status in {"queued", "running"}:
            any_running = True
            all_completed = False
            previous_open_blocker = sid
        elif status == "failed":
            any_failed = True
            all_completed = False
            previous_failed_blocker = sid
            if blocked_on is None:
                blocked_on = sid
                blocked_reason = reason or "failed"
        elif status in {"blocked", "pending"}:
            all_completed = False
            if blocked_on is None:
                blocked_on = sid
                blocked_reason = reason or "blocked"
            previous_open_blocker = sid
        elif status == "completed":
            pass
        elif status == "skipped":
            pass

        rows.append({
            "subtask_id": sid,
            "status": status,
            "queue_id": queue_id_value,
            "task_id": task_id_value,
            "reason": reason,
        })

    if plan.get("status") == "draft":
        status = "draft"
    elif any_failed:
        status = "blocked"
    elif any_running:
        status = "running"
    elif all_completed:
        status = "completed"
    elif any(r["status"] in {"queued", "completed", "skipped"} for r in rows):
        status = "approved"
    else:
        status = "approved"

    return {
        "plan_id": plan.get("plan_id"),
        "status": status,
        "subtasks": rows,
        "blocked_on": blocked_on,
        "blocked_reason": blocked_reason,
    }

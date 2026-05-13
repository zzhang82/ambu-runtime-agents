import datetime as dt


def cron_field_matches(value, field):
    field = str(field).strip()
    if field == "*":
        return True
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                return step > 0 and value % step == 0
            except ValueError:
                return False
        if "-" in part:
            try:
                start, end = [int(x) for x in part.split("-", 1)]
                if start <= value <= end:
                    return True
            except ValueError:
                return False
        else:
            try:
                if int(part) == value:
                    return True
            except ValueError:
                return False
    return False


def cron_matches_now(expr, when=None):
    when = when or dt.datetime.now().astimezone()
    fields = str(expr).split()
    if len(fields) != 5:
        raise ValueError("cron must have five fields: minute hour day month weekday")
    minute, hour, day, month, weekday = fields
    cron_weekday = (when.weekday() + 1) % 7
    return (
        cron_field_matches(when.minute, minute)
        and cron_field_matches(when.hour, hour)
        and cron_field_matches(when.day, day)
        and cron_field_matches(when.month, month)
        and cron_field_matches(cron_weekday, weekday)
    )


def due_window_id(when=None):
    when = when or dt.datetime.now().astimezone()
    return when.strftime("%Y%m%d%H%M")


def schedule_due(schedule, when=None):
    when = when or dt.datetime.now().astimezone()
    if not schedule.get("enabled", True):
        return False, "disabled"
    try:
        matches = cron_matches_now(schedule.get("cron"), when)
    except Exception as exc:
        return False, f"invalid_cron: {exc}"
    if not matches:
        return False, "not_due"
    window = due_window_id(when)
    if schedule.get("last_due_window") == window:
        return False, "already_submitted_for_due_window"
    return True, window

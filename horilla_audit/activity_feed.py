"""
Normalize simple-history / auditlog diffs into one activity-feed context.
"""

from datetime import timedelta

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.utils.translation import gettext as _


def history_action_phrase(changes, fallback=None):
    """Short activity-feed phrase from changed fields (e.g. 'updated department')."""
    if fallback:
        return fallback
    if not changes:
        return _("updated record")
    labels = [
        str(c.get("field_label") or c.get("field") or c.get("field_name") or "").strip()
        for c in changes
    ]
    labels = [label for label in labels if label]
    if not labels:
        return _("updated record")
    first = labels[0]
    if len(labels) == 1:
        return _("updated %(field)s") % {"field": first.lower()}
    if len(labels) == 2:
        return _("updated %(first)s and %(second)s") % {
            "first": first.lower(),
            "second": labels[1].lower(),
        }
    return _("updated %(field)s and %(count)s other fields") % {
        "field": first.lower(),
        "count": len(labels) - 1,
    }


def history_date_label(history_date, today=None):
    """Group header: Today / Yesterday / full date."""
    if history_date is None:
        return _("Unknown date")
    if timezone.is_aware(history_date):
        local_dt = timezone.localtime(history_date)
    else:
        local_dt = history_date
    day = local_dt.date() if hasattr(local_dt, "date") else local_dt
    today = today or timezone.localdate()
    if day == today:
        return _("Today")
    if day == today - timedelta(days=1):
        return _("Yesterday")
    return day.strftime("%b %d, %Y")


def _is_system_actor(updated_by):
    return updated_by is None or getattr(updated_by, "is_system_actor", False)


def _actor_name(updated_by):
    if _is_system_actor(updated_by):
        return _("System update")
    if hasattr(updated_by, "get_full_name"):
        return updated_by.get_full_name() or str(updated_by)
    return str(updated_by) or _("System update")


def _actor_avatar(updated_by):
    if _is_system_actor(updated_by):
        return None
    getter = getattr(updated_by, "get_avatar", None)
    if callable(getter):
        return getter()
    return None


def _normalize_tracking_change(change, pair=None):
    """Ensure change dict has labels/display values used by the feed template."""
    normalized = dict(change)
    label = (
        normalized.get("field_label")
        or normalized.get("field")
        or normalized.get("field_name")
        or ""
    )
    normalized["field_label"] = label
    for side, index in (("old", 1), ("new", 0)):
        display_key = f"{side}_value"
        raw = normalized.get(side, normalized.get(display_key))
        empty = raw in (None, "")
        normalized[f"{side}_is_empty"] = empty
        if empty:
            if normalized.get("is_fk"):
                normalized[display_key] = (
                    _("Previously unassigned") if side == "old" else _("Unassigned")
                )
            else:
                normalized[display_key] = _("Not set")
        elif display_key not in normalized:
            value = raw
            if normalized.get("is_fk") and pair and len(pair) > index:
                try:
                    related = getattr(pair[index], normalized["field_name"])
                    value = related if related is not None else f"{raw} (deleted)"
                except (AttributeError, ObjectDoesNotExist):
                    value = f"{raw} (deleted)"
            normalized[display_key] = str(value)
    return normalized


def normalize_tracking_entries(tracking):
    """Convert get_diff()-style tracking list into feed entries."""
    entries = []
    for history in tracking or []:
        pair = history.get("pair")
        changes = [
            _normalize_tracking_change(c, pair) for c in (history.get("changes") or [])
        ]
        newer = pair[0] if pair else None
        history_date = getattr(newer, "history_date", None) if newer else None
        updated_by = history.get("updated_by")
        reason = None
        if newer is not None:
            reason = (
                getattr(newer, "history_title", None)
                or history.get("change_reason")
                or getattr(newer, "history_change_reason", None)
            )
        else:
            reason = history.get("change_reason")

        event_type = history.get("type") or ""
        history_type = getattr(newer, "history_type", None) if newer else None

        # Keep create/update snapshots even when there is no field-level diff.
        # Attendance and similar models often only store a single "~" row.
        if not changes:
            if event_type and event_type != "Changes":
                pass  # keep typed events like "Leave request created"
            elif history_type == "+":
                event_type = event_type or _("record created")
            elif history_type == "~" or event_type == "Changes":
                event_type = _("record updated")
            elif event_type:
                pass
            else:
                continue

        action_phrase = history_action_phrase(
            changes,
            fallback=(
                str(event_type).lower()
                if event_type and event_type != "Changes"
                else None
            ),
        )
        entries.append(
            {
                **history,
                "changes": changes,
                "history_date": history_date,
                "action_phrase": action_phrase,
                "actor_name": _actor_name(updated_by),
                "actor_avatar": _actor_avatar(updated_by),
                "is_system_actor": _is_system_actor(updated_by),
                "reason": reason,
                "change_count": len(changes),
                "source": "tracking",
                "revert_history_id": (
                    getattr(pair[1], "pk", None)
                    if pair and len(pair) > 1 and pair[0] != pair[1]
                    else None
                ),
            }
        )
    return entries


class _AuditActor:
    """Minimal actor shape for auditlog entries in the shared feed."""

    def __init__(self, employee=None, name=None):
        self.employee = employee
        self.is_system_actor = employee is None and not name
        self.name = name or _("System update")

    def get_full_name(self):
        if self.employee and hasattr(self.employee, "get_full_name"):
            return self.employee.get_full_name()
        return self.name

    def get_avatar(self):
        if self.employee and hasattr(self.employee, "get_avatar"):
            return self.employee.get_avatar()
        return f"https://ui-avatars.com/api/?name={self.name.replace(' ', '+')}&background=random"

    def __str__(self):
        return self.get_full_name()


def normalize_log_entries(log_entries):
    """Convert django-auditlog LogEntry queryset/list into feed entries."""
    entries = []
    for entry in log_entries or []:
        employee = None
        actor = getattr(entry, "actor", None)
        if actor is not None:
            employee = getattr(actor, "employee_get", None)
        updated_by = _AuditActor(
            employee=employee,
            name=_actor_name(actor) if actor is not None else None,
        )

        changes = []
        display = getattr(entry, "changes_display_dict", None) or {}
        for field, values in display.items():
            if not values or values[0] == "type":
                continue
            old_val = values[0] if len(values) > 0 else "—"
            new_val = values[1] if len(values) > 1 else "—"
            changes.append(
                _normalize_tracking_change(
                    {
                        "field": field,
                        "field_label": field,
                        "field_name": field,
                        "is_fk": False,
                        "old_value": old_val,
                        "new_value": new_val,
                    }
                )
            )

        action = getattr(entry, "action", None)
        if action == 0:
            fallback = _("created record")
        elif action == 2:
            fallback = _("deleted record")
        else:
            fallback = None

        if not changes and fallback is None:
            continue

        entries.append(
            {
                "type": "Changes",
                "pair": None,
                "changes": changes,
                "updated_by": updated_by,
                "history_date": getattr(entry, "timestamp", None),
                "action_phrase": history_action_phrase(changes, fallback=fallback),
                "actor_name": _actor_name(updated_by),
                "actor_avatar": _actor_avatar(updated_by),
                "is_system_actor": _is_system_actor(updated_by),
                "reason": None,
                "change_count": len(changes),
                "source": "auditlog",
                "revert_history_id": None,
            }
        )
    return entries


def group_history_entries(entries):
    """Group normalized entries under Today / Yesterday / date labels."""
    today = timezone.localdate()
    grouped = {}
    group_order = []
    for entry in entries:
        label = history_date_label(entry.get("history_date"), today=today)
        if label not in grouped:
            grouped[label] = []
            group_order.append(label)
        grouped[label].append(entry)
    return [{"label": label, "entries": grouped[label]} for label in group_order]


def build_activity_history_feed(tracking=None, log_entries=None):
    """
    Build the shared activity-history context used by templates / inclusion tags.
    Prefers simple-history tracking when present; otherwise uses auditlog entries.
    """
    if tracking:
        entries = normalize_tracking_entries(tracking)
    else:
        entries = normalize_log_entries(log_entries)

    history_groups = group_history_entries(entries)
    return {
        "has_history": bool(entries),
        "history_groups": history_groups,
        "filtered_empty": False,
        "search": "",
    }

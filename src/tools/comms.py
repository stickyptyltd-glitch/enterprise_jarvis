"""Communications and scheduling domain tools."""

from src.tools.base import STORE


def list_schedule() -> str:
    """List upcoming meetings and calendar events."""
    text = "\n".join(f"  - {s['id']} | {s['when']} | {s['title']} | {', '.join(s['attendees'])}" for s in STORE.data["schedule"])
    return f"Upcoming schedule ({len(STORE.data['schedule'])}):\n{text}"


def draft_email(recipient: str, topic: str) -> str:
    """Draft an email message to a recipient about a given topic (does not send)."""
    return (
        f"DRAFT to {recipient}\n"
        f"Subject: {topic}\n"
        f"Hi {recipient.title().split()[0]},\n\n"
        f"Following up regarding: {topic}. Please let me know a good time to connect.\n\n"
        f"Best,\nExecutive Office"
    )


def send_email(recipient: str, subject: str, body: str) -> str:
    """Send an email message to a recipient. High-risk action requiring HITL approval."""
    STORE.notify(f"Email sent to {recipient}: '{subject}'.")
    STORE.save()
    return f"Email sent to {recipient} with subject '{subject}'."


def schedule_meeting(title: str, when: str, attendees: str) -> str:
    """Add a meeting to the company calendar. High-risk action requiring HITL approval."""
    entry = {"id": f"S-{len(STORE.data['schedule']) + 1:02d}", "title": title, "when": when, "attendees": [a.strip() for a in attendees.split(",")]}
    STORE.data["schedule"].append(entry)
    STORE.notify(f"Meeting scheduled: {title} at {when}.")
    STORE.save()
    return f"Scheduled '{title}' for {when} with {entry['attendees']}."


def send_reminder(attendee: str, subject: str) -> str:
    """Send a reminder to an attendee about an upcoming item. High-risk action requiring HITL approval."""
    STORE.notify(f"Reminder sent to {attendee} regarding '{subject}'.")
    STORE.save()
    return f"Reminder sent to {attendee} about '{subject}'."


from src.tools.base import register_critical  # noqa: E402

register_critical("send_email", "schedule_meeting", "send_reminder")
"""Send a change-only registry digest through authenticated SMTP.

Required environment: SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
SMTP_FROM, ALERT_TO. Never print credentials or email contents in CI logs.
"""
import datetime as dt
import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "state.json"
CURSOR = ROOT / "data" / "email-cursor.json"
FEED = "https://jessica-lsd.github.io/non-us-idh-trial-watch/feed.xml"

def main():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    cursor = json.loads(CURSOR.read_text(encoding="utf-8")) if CURSOR.exists() else {}
    seen = set(cursor.get("sent_guids", []))
    # Baseline entries are never emailed; historical events are not replayed.
    events = [e for e in state.get("events", [])
              if e.get("kind") in ("New trial", "Material change")
              and e.get("guid") not in seen]
    if not events:
        print("No unsent material trial changes; no email.")
        return
    names = ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "ALERT_TO")
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError("Email credentials are not configured: " + ", ".join(missing))
    lines = ["Non-US IDH Clinical Trial Surveillance",
             f"{len(events)} new or materially changed trial record(s).", ""]
    for e in events:
        lines.append(f"{e['kind']} | observed {e['observed']}")
        lines.append("Changed fields: " + ", ".join(e.get("changes", [])))
        for r in e.get("records", []):
            lines.append(f"  {r.get('source', '')} | {r.get('id', '')} | {', '.join(r.get('assets', []))}")
            for field in ("indications", "phase", "status", "registered", "start", "primary_completion", "completion"):
                value = r.get(field) or "Not supplied"
                lines.append(f"  {field}: {value}")
            lines.append("  Registry: " + r.get("url", ""))
        lines.append("")
    lines += ["Coverage is partial; check the coverage page for source failures.",
              FEED, "https://jessica-lsd.github.io/non-us-idh-trial-watch/"]
    msg = EmailMessage()
    msg["Subject"] = f"IDH Clinical Trial Surveillance — {len(events)} update(s)"
    msg["From"] = os.environ["SMTP_FROM"]
    msg["To"] = os.environ["ALERT_TO"]
    msg.set_content("\n".join(lines))
    host, port = os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
    # Cursor is persisted only after SMTP accepts the message.
    cursor["sent_guids"] = list(dict.fromkeys([*cursor.get("sent_guids", []), *(e["guid"] for e in events)]))
    cursor["last_sent_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    CURSOR.parent.mkdir(exist_ok=True)
    CURSOR.write_text(json.dumps(cursor, indent=2) + "\n", encoding="utf-8")
    print(f"Email accepted by SMTP for {len(events)} change(s).")

if __name__ == "__main__":
    main()

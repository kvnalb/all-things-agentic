from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .cloud import Secrets, Settings, State
from .models import StudyBlock, Task


SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile", "https://www.googleapis.com/auth/calendar.app.created", "https://www.googleapis.com/auth/calendar.calendarlist.readonly"]
CALENDAR_MARKER = "studyagent-fall-2026-v1"


class Google:
    def __init__(self) -> None:
        self.secrets = Secrets(); self.state = State()

    def start_url(self) -> str:
        state, verifier = self.state.create_oauth_state(); config = json.loads(self.secrets.read(Settings.oauth_client_secret))
        flow = Flow.from_client_config(config, scopes=SCOPES, redirect_uri=f"{Settings.base_url}/api/auth/google/callback", code_verifier=verifier, autogenerate_code_verifier=False)
        url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true", state=state)
        return url

    def callback(self, state: str, code: str) -> str:
        verifier = self.state.consume_oauth_state(state)
        if not verifier: raise ValueError("OAuth state is invalid or expired")
        config = json.loads(self.secrets.read(Settings.oauth_client_secret)); flow = Flow.from_client_config(config, scopes=SCOPES, state=state, redirect_uri=f"{Settings.base_url}/api/auth/google/callback", code_verifier=verifier, autogenerate_code_verifier=False)
        flow.fetch_token(code=code); credentials = flow.credentials
        response = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {credentials.token}"}, timeout=15); response.raise_for_status(); email = response.json().get("email", "")
        if email.casefold() != Settings.allowed_email.casefold(): raise PermissionError("This Google account is not the configured owner")
        version = self.secrets.add(Settings.oauth_token_secret, credentials.to_json()); calendar_id = self._calendar(credentials)
        self.state.save_connection({"email": email, "token_secret_version": version, "calendar_id": calendar_id, "connected_at": datetime.now(UTC)})
        return self.state.create_session(email)

    def credentials(self) -> Credentials:
        version = self.state.connection().get("token_secret_version")
        if not version: raise RuntimeError("Google is not connected")
        return Credentials.from_authorized_user_info(json.loads(self.secrets.read(version)), SCOPES)

    def _calendar(self, credentials: Credentials) -> str:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False); token = None
        while True:
            page = service.calendarList().list(pageToken=token).execute()
            for item in page.get("items", []):
                if item.get("summary") == Settings.calendar_name and item.get("description") == CALENDAR_MARKER: return item["id"]
            token = page.get("nextPageToken")
            if not token: break
        return service.calendars().insert(body={"summary": Settings.calendar_name, "description": CALENDAR_MARKER, "timeZone": "America/Los_Angeles"}).execute()["id"]


class CalendarWriter:
    def __init__(self) -> None:
        self.state = State(); self.db = self.state.db

    def sync_donor_blocks(self, placements: list[dict], run_id: str) -> dict[str, int]:
        connection = self.state.connection(); calendar_id = connection.get("calendar_id")
        if not calendar_id: raise RuntimeError("Google is not connected")
        service = build("calendar", "v3", credentials=Google().credentials(), cache_discovery=False)
        counts = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0}; desired: set[str] = set()
        for placement in placements:
            task = placement["task"]; task_key = f"{task.source}:{task.source_ref}"
            key = f"work:{task_key}:{placement['block_index']}"; desired.add(key)
            start, end = placement["start"], placement["end"]; due_local = task.due_at.astimezone()
            body = {
                "summary": f"Work: {task.title} ({task.course})",
                "description": (
                    f"Auto-scheduled by Taskmaster. Rank {task.priority_score}. "
                    f"Due {due_local:%a %b %d %I:%M %p}."
                ),
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
                "colorId": placement["color_id"],
            }
            counts[self._write(service, calendar_id, key, body, run_id)] += 1
        counts["deleted"] = self._delete_stale(service, calendar_id, desired, run_id)
        return counts

    def sync(self, tasks: list[Task], blocks: list[StudyBlock], run_id: str) -> dict[str, int]:
        connection = self.state.connection(); calendar_id = connection.get("calendar_id")
        if not calendar_id: raise RuntimeError("Google is not connected")
        service = build("calendar", "v3", credentials=Google().credentials(), cache_discovery=False); counts = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0}; desired: set[str] = set()
        for task in tasks:
            if task.submitted: continue
            start = task.due_at
            schedule = ({"start": {"date": start.date().isoformat()}, "end": {"date": (start.date() + timedelta(days=1)).isoformat()}} if task.date_only else {"start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(minutes=15)).isoformat()}})
            provenance = {"candidate_id": task.candidate_id or task.source_ref}
            if task.source_revision_id: provenance["source_revision_id"] = task.source_revision_id
            body = {"summary": f"[DUE] {task.title}", "description": f"Course: {task.course}\nSource: {task.source_url or task.source}\nDue date managed by StudyAgent.", "_private": provenance, **schedule}
            key = f"deadline:{task.key}"; desired.add(key)
            counts[self._write(service, calendar_id, key, body, run_id)] += 1
        for block in blocks:
            body = {"summary": f"{block.title} ({block.course})", "description": f"Recommended by StudyAgent. Priority {block.priority_score}.\nSource: {block.source_url or block.task_key}", "start": {"dateTime": block.start_at.isoformat()}, "end": {"dateTime": block.end_at.isoformat()}, "colorId": block.color_id}
            key = f"study:{block.key}"; desired.add(key)
            counts[self._write(service, calendar_id, key, body, run_id)] += 1
        counts["deleted"] = self._delete_stale(service, calendar_id, desired, run_id)
        return counts

    def _delete_stale(self, service, calendar_id: str, desired: set[str], run_id: str) -> int:
        deleted = 0
        for snapshot in self.db.collection("calendar_bindings").stream():
            binding = snapshot.to_dict() or {}; key = binding.get("key")
            if not key or key in desired: continue
            snapshot.reference.set({"state": "deleting", "run_id": run_id, "attempted_at": datetime.now(UTC)}, merge=True)
            try:
                service.events().delete(calendarId=calendar_id, eventId=binding["google_event_id"]).execute()
            except HttpError as exc:
                if exc.resp.status != 404: raise
            snapshot.reference.delete(); deleted += 1
        return deleted

    def _write(self, service, calendar_id: str, key: str, body: dict, run_id: str) -> str:
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(); doc_id = hashlib.sha256(key.encode()).hexdigest()[:24]
        ref = self.db.collection("calendar_bindings").document(doc_id); binding = ref.get().to_dict() or {}
        if binding.get("desired_hash") == digest: return "skipped"
        private = {"studyagent_key": key, "run_id": run_id}
        if key.startswith("deadline:"):
            # The deadline body is built from a Task, whose provenance is added
            # by sync() before calling this helper.
            private.update(body.pop("_private", {}))
        body["extendedProperties"] = {"private": private}
        ref.set({"key": key, "state": "writing", "desired_hash": digest, "run_id": run_id, "attempted_at": datetime.now(UTC)}, merge=True)
        if binding.get("google_event_id"):
            result = service.events().patch(calendarId=calendar_id, eventId=binding["google_event_id"], body=body).execute(); action = "updated"
        else:
            result = service.events().insert(calendarId=calendar_id, body=body).execute(); action = "created"
        ref.set({"key": key, "google_event_id": result["id"], "desired_hash": digest, "run_id": run_id, "state": "synced", "synced_at": datetime.now(UTC)})
        return action

from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta

from google.cloud import firestore, secretmanager

from .models import Task, UserConfig


class Settings:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    bucket = os.environ.get("STUDYAGENT_SOURCE_BUCKET", "")
    base_url = os.environ.get("STUDYAGENT_BASE_URL", "http://localhost:8080").rstrip("/")
    allowed_email = os.environ.get("STUDYAGENT_ALLOWED_EMAIL", "")
    canvas_base_url = os.environ.get("CANVAS_BASE_URL", "https://bcourses.berkeley.edu").rstrip("/")
    canvas_secret = "studyagent-canvas-token"
    oauth_client_secret = "studyagent-google-oauth-client"
    oauth_token_secret = "studyagent-google-oauth-token"
    calendar_name = "StudyAgent — Fall 2026"

    @classmethod
    def require(cls) -> None:
        if not all((cls.project, cls.bucket, cls.allowed_email)):
            raise RuntimeError("StudyAgent cloud configuration is incomplete")


class Secrets:
    def __init__(self) -> None:
        Settings.require(); self.client = secretmanager.SecretManagerServiceClient()

    def read(self, name: str) -> str:
        resource = name if "/versions/" in name else f"projects/{Settings.project}/secrets/{name}/versions/latest"
        return self.client.access_secret_version(request={"name": resource}, timeout=15).payload.data.decode()

    def add(self, name: str, value: str) -> str:
        parent = f"projects/{Settings.project}/secrets/{name}"
        return self.client.add_secret_version(request={"parent": parent, "payload": {"data": value.encode()}}, timeout=15).name


class State:
    def __init__(self) -> None:
        Settings.require(); self.db = firestore.Client(project=Settings.project)

    def config(self) -> UserConfig:
        value = self.db.collection("config").document("owner").get().to_dict() or {}
        return UserConfig.model_validate(value)

    def save_config(self, config: UserConfig) -> None:
        self.db.collection("config").document("owner").set(config.model_dump(mode="json"))

    def task(self, key: str) -> Task | None:
        snap = self.db.collection("tasks").document(hashlib.sha256(key.encode()).hexdigest()[:24]).get()
        return Task.model_validate(snap.to_dict()) if snap.exists else None

    def save_tasks(self, tasks: list[Task]) -> None:
        if not tasks: return
        batch = self.db.batch()
        for task in tasks:
            ref = self.db.collection("tasks").document(hashlib.sha256(task.key.encode()).hexdigest()[:24])
            batch.set(ref, {**task.model_dump(mode="json", exclude_none=True), "updated_at": datetime.now(UTC)}, merge=True)
        batch.commit()

    def checkpoints(self) -> dict[str, str]:
        return (self.db.collection("config").document("source_checkpoints").get().to_dict() or {}).get("revisions", {})

    def save_checkpoints(self, revisions: dict[str, str]) -> None:
        self.db.collection("config").document("source_checkpoints").set({"revisions": revisions, "updated_at": datetime.now(UTC)})

    def list_tasks(self) -> list[Task]:
        return [Task.model_validate(s.to_dict()) for s in self.db.collection("tasks").stream()]

    def start_run(self, trigger: str) -> tuple[str, firestore.DocumentReference]:
        run_id = secrets.token_hex(12); ref = self.db.collection("runs").document(run_id)
        ref.set({"run_id": run_id, "trigger": trigger, "state": "running", "started_at": datetime.now(UTC)})
        return run_id, ref

    def status(self) -> dict:
        runs = list(self.db.collection("runs").order_by("started_at", direction=firestore.Query.DESCENDING).limit(1).stream())
        last = runs[0].to_dict() if runs else None
        return {"google_connected": self.db.collection("connections").document("google").get().exists, "canvas_connected": bool(self.config().selected_course_ids), "last_run": last, "next_sync_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}

    def activity(self, limit: int = 20) -> list[dict]:
        return [snap.to_dict() for snap in self.db.collection("runs").order_by("started_at", direction=firestore.Query.DESCENDING).limit(limit).stream()]

    def create_session(self, email: str) -> str:
        token = secrets.token_urlsafe(32); digest = hashlib.sha256(token.encode()).hexdigest()
        self.db.collection("sessions").document(digest).set({"email": email, "expires_at": datetime.now(UTC) + timedelta(days=7)})
        return token

    def valid_session(self, token: str | None) -> bool:
        if not token: return False
        value = self.db.collection("sessions").document(hashlib.sha256(token.encode()).hexdigest()).get().to_dict() or {}
        return bool(value.get("expires_at") and value["expires_at"] > datetime.now(UTC) and value.get("email", "").casefold() == Settings.allowed_email.casefold())

    def create_oauth_state(self) -> tuple[str, str]:
        value = secrets.token_urlsafe(32); verifier = secrets.token_urlsafe(64)
        self.db.collection("oauth_states").document(value).set({"used": False, "code_verifier": verifier, "expires_at": datetime.now(UTC) + timedelta(minutes=10)})
        return value, verifier

    def consume_oauth_state(self, value: str) -> str | None:
        ref = self.db.collection("oauth_states").document(value); snap = ref.get(); data = snap.to_dict() or {}
        if not snap.exists or data.get("used") or data.get("expires_at", datetime.min.replace(tzinfo=UTC)) < datetime.now(UTC): return None
        verifier = data.get("code_verifier")
        if not verifier: return None
        ref.set({"used": True, "code_verifier": firestore.DELETE_FIELD}, merge=True); return verifier

    def connection(self) -> dict:
        return self.db.collection("connections").document("google").get().to_dict() or {}

    def save_connection(self, value: dict) -> None:
        self.db.collection("connections").document("google").set(value, merge=True)

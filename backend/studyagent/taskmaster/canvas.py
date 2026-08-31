from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import httpx

from .cloud import Secrets, Settings
from .models import Task


TEACHING_ROLES = {"ta", "teacher", "designer"}


class Canvas:
    def __init__(self) -> None:
        self.token = Secrets().read(Settings.canvas_secret)

    def get(self, path: str, params: dict | None = None, *, optional: bool = False):
        url = urljoin(f"{Settings.canvas_base_url}/", f"api/v1/{path.lstrip('/')}"); values = []
        with httpx.Client(timeout=20, follow_redirects=False, headers={"Authorization": f"Bearer {self.token}"}) as client:
            while url:
                response = client.get(url, params=params); params = None
                if optional and response.status_code in {403, 404}: return []
                if response.status_code == 401: raise RuntimeError("Canvas token is invalid or expired")
                response.raise_for_status(); payload = response.json()
                if not isinstance(payload, list): return payload
                values.extend(payload); next_url = response.links.get("next", {}).get("url")
                if next_url and not next_url.startswith(f"{Settings.canvas_base_url}/"): raise RuntimeError("Canvas returned unsafe pagination")
                url = next_url
        return values

    @staticmethod
    def role(course: dict) -> str:
        roles = [str(e.get("type", "")).lower().replace("enrollment", "") for e in course.get("enrollments") or []]
        return next((role for role in roles if role in TEACHING_ROLES), roles[0] if roles else "unknown")

    def download(self, url: str) -> httpx.Response | None:
        if not url.startswith(f"{Settings.canvas_base_url}/"):
            raise RuntimeError("Canvas returned an unsafe file URL")
        response = httpx.get(url, headers={"Authorization": f"Bearer {self.token}"}, timeout=30, follow_redirects=True)
        if response.status_code in {403, 404}: return None
        response.raise_for_status(); return response

    def discover(self) -> tuple[str, list[dict]]:
        profile = self.get("users/self/profile")
        courses = self.get("courses", {"enrollment_state": "active", "include[]": ["term", "enrollments"], "per_page": 100})
        fall = [{"id": str(c["id"]), "code": c.get("course_code") or "", "title": c.get("name") or c.get("course_code") or str(c["id"]), "term": (c.get("term") or {}).get("name", "Fall 2026"), "role": self.role(c)} for c in courses if "fall 2026" in f"{(c.get('term') or {}).get('name','')} {c.get('name','')}".lower()]
        return profile.get("name", "Canvas user"), fall

    def tasks(self, selected: list[str]) -> tuple[list[Task], list[dict]]:
        tasks: list[Task] = []; syllabi = []
        courses = {str(c["id"]): c for c in self.get("courses", {"enrollment_state": "active", "include[]": ["term", "enrollments"], "per_page": 100})}
        for course_id in selected:
            course = courses.get(course_id)
            if not course or self.role(course) in TEACHING_ROLES: continue
            name = course.get("name") or course.get("course_code") or course_id
            detail = self.get(f"courses/{course_id}", {"include[]": "syllabus_body"})
            if detail.get("syllabus_body"): syllabi.append({"course_id": course_id, "course": name, "filename": "canvas-syllabus.html", "content": detail["syllabus_body"].encode(), "media_type": "text/html"})
            assignments = self.get(f"courses/{course_id}/assignments", {"include[]": "submission", "per_page": 100})
            for item in assignments:
                if not item.get("due_at"): continue
                submission = item.get("submission") or {}; submitted = bool(submission.get("submitted_at") or submission.get("workflow_state") in {"submitted", "graded", "complete"})
                tasks.append(Task(source="canvas", source_ref=str(item["id"]), title=item.get("name") or "Untitled assignment", course=name, description=(item.get("description") or "")[:4000], due_at=datetime.fromisoformat(item["due_at"].replace("Z", "+00:00")), source_url=item.get("html_url"), points_possible=item.get("points_possible"), submitted=submitted))
            self.get(f"courses/{course_id}/quizzes", {"per_page": 100}, optional=True)
            for file in self.get(f"courses/{course_id}/files", {"per_page": 100}, optional=True):
                filename = file.get("display_name") or ""
                if "syllabus" not in filename.casefold() or not filename.casefold().endswith((".pdf", ".md", ".txt", ".html")): continue
                response = self.download(file["url"])
                if response is None: continue
                syllabi.append({"course_id": course_id, "course": name, "filename": filename, "content": response.content, "media_type": response.headers.get("content-type")})
        return tasks, syllabi

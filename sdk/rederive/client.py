"""HTTP client for the Rederive server."""

import time
from typing import Any

import httpx

from rederive.exposure import current_tool_call
from rederive.recipes import Recipe


class RederiveError(Exception):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def ref(record: dict | str, version: int | None = None) -> str:
    """Build an input reference: "id" or "id@version"."""
    if isinstance(record, dict):
        return f"{record['id']}@{record['version']}"
    return f"{record}@{version}" if version is not None else str(record)


class Rederive:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 120.0,
                 http: httpx.Client | None = None):
        # `http` lets tests pass a FastAPI TestClient.
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Rederive":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _call(self, method: str, path: str, **kwargs) -> Any:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except ValueError:
                detail = resp.text
            raise RederiveError(resp.status_code, detail)
        return resp.json()

    # -- writes -------------------------------------------------------------

    def observe(self, text: str, **meta: Any) -> dict:
        return self._call("POST", "/records/observe", json={"text": text, "meta": meta})

    def derive(self, inputs: list[dict | str], recipe: Recipe, kind: str = "summary",
               target_id: str | None = None, fan_in_k: int | None = None, **meta: Any) -> dict:
        body = {
            "inputs": [ref(i) if isinstance(i, dict) else i for i in inputs],
            "recipe": recipe.to_json(),
            "kind": kind,
            "meta": meta,
            "target_id": target_id,
            "fan_in_k": fan_in_k,
        }
        return self._call("POST", "/records/derive", json=body)

    def retract(self, record_id: str) -> dict:
        return self._call("POST", f"/records/{record_id}/retract")

    def correct(self, record_id: str, text: str) -> dict:
        return self._call("POST", f"/records/{record_id}/correct", json={"text": text})

    def delete(self, record_id: str, payload: str | None = None) -> dict:
        return self._call("POST", f"/records/{record_id}/delete", json={"payload": payload})

    # -- reads --------------------------------------------------------------

    def read(self, record_id: str, version: int | None = None) -> dict:
        params: dict[str, Any] = {}
        if version is not None:
            params["version"] = version
        call = current_tool_call()
        if call is not None:
            params["tool_call_id"] = call.id
            params["tool_name"] = call.name
        rec = self._call("GET", f"/records/{record_id}", params=params)
        if call is not None:
            call.reads.append((rec["id"], rec["version"]))
        return rec

    def versions(self, record_id: str) -> list[dict]:
        return self._call("GET", f"/records/{record_id}/versions")

    def lineage(self, record_id: str, version: int | None = None) -> dict:
        params = {"version": version} if version is not None else {}
        return self._call("GET", f"/records/{record_id}/lineage", params=params)

    def diff(self, record_id: str, from_version: int, to_version: int) -> dict:
        return self._call("GET", f"/records/{record_id}/diff",
                          params={"from": from_version, "to": to_version})

    def exposures(self, stale_only: bool = True) -> list[dict]:
        return self._call("GET", "/exposure", params={"stale_only": stale_only})

    def deletion_report(self, record_id: str) -> dict:
        return self._call("GET", f"/records/{record_id}/deletion_report")

    def graph(self, user: str | None = None) -> dict:
        return self._call("GET", "/graph", params={"user": user} if user else {})

    def jobs(self) -> dict:
        return self._call("GET", "/jobs")

    def reset(self) -> dict:
        return self._call("POST", "/admin/reset")

    def wait_idle(self, timeout: float = 60.0, poll: float = 0.1) -> dict:
        """Block until no rebuild job is queued or running. Returns job counts."""
        deadline = time.monotonic() + timeout
        while True:
            summary = self.jobs()["summary"]
            if not summary.get("queued") and not summary.get("running"):
                return summary
            if time.monotonic() > deadline:
                raise TimeoutError(f"rebuild jobs still pending: {summary}")
            time.sleep(poll)

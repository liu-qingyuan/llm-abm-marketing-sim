from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from llm_abm_sim import __version__
from llm_abm_sim.safe_serialization import safe_data
from llm_abm_sim.web.imports import validate_upload_files
from llm_abm_sim.web.service import ARTIFACT_ALLOWLIST, WebRunStore


def create_app(*, artifact_root: str | Path | None = None) -> FastAPI:
    root = Path(artifact_root or "runs/web").resolve()
    store = WebRunStore(root)
    app = FastAPI(title="LLM-ABM Local Web Console", version=__version__)
    app.state.web_store = store
    static_dir = Path(__file__).resolve().parents[1] / "web_static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (static_dir / "index.html").read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "artifact_root": str(root),
            "mock_provider_available": True,
            "artifact_allowlist": sorted(ARTIFACT_ALLOWLIST),
        }

    @app.post("/api/datasets/validate")
    async def validate_dataset(
        users_file: Annotated[UploadFile, File()],
        edges_file: Annotated[UploadFile, File()],
        seed_user_ids: Annotated[str, Form()] = "",
    ) -> JSONResponse:
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                users_path = tmp_path / _safe_upload_name(users_file.filename or "users")
                edges_path = tmp_path / _safe_upload_name(edges_file.filename or "edges")
                await _save_upload(users_file, users_path)
                await _save_upload(edges_file, edges_path)
                upload = validate_upload_files(
                    root_dir=root,
                    users_filename=users_file.filename or users_path.name,
                    users_source=users_path,
                    edges_filename=edges_file.filename or edges_path.name,
                    edges_source=edges_path,
                    seed_user_ids=_split(seed_user_ids),
                )
                store.add_dataset(upload)
                payload = {
                    "valid": not upload.validation_report.errors,
                    "validation_id": upload.validation_id,
                    "dataset_validation": upload.safe_report(),
                    "preview": {
                        "profile_count": upload.validation_report.profile_count,
                        "edge_count": upload.validation_report.graph_edge_count,
                        "missing_seed_user_ids": upload.validation_report.missing_seed_user_ids,
                        "preserved_profile_attribute_columns": upload.safe_report().get(
                            "preserved_profile_attribute_columns", []
                        ),
                    },
                }
                return JSONResponse(safe_data(payload))
        except Exception as exc:  # noqa: BLE001 - user-facing upload diagnostics.
            return JSONResponse(
                status_code=400,
                content=safe_data(
                    {
                        "valid": False,
                        "error": {"class": exc.__class__.__name__, "message": _safe_message(exc)},
                    }
                ),
            )

    @app.get("/api/provider/readiness")
    def provider_readiness(mock_provider: bool = Query(default=False)) -> dict[str, Any]:
        return store.provider_readiness(mock_provider=mock_provider)

    @app.post("/api/runs")
    async def create_run(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="request JSON must be an object")
        job = store.create_run(payload)
        return job.to_dict()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        job = store.get_job(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail="run not found")
        return job.to_dict()

    @app.get("/api/runs/{run_id}/report-payload")
    def get_report_payload(run_id: str) -> dict[str, Any]:
        try:
            return store.report_payload(run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/artifact/{name}")
    def get_artifact(run_id: str, name: str) -> FileResponse:
        try:
            path = store.artifact_path(run_id, name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        media_type = "text/html" if path.suffix == ".html" else None
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.get("/api/templates/{name}")
    def get_template(name: str) -> FileResponse:
        templates = {
            "users.csv": Path("configs/templates/web_users.csv"),
            "edges.csv": Path("configs/templates/web_edges.csv"),
            "users.json": Path("configs/templates/web_users.json"),
            "edges.json": Path("configs/templates/web_edges.json"),
        }
        path = templates.get(name)
        if path is None or not path.exists():
            raise HTTPException(status_code=404, detail="template not found")
        return FileResponse(path, filename=name)

    return app


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            handle.write(chunk)
    await upload.close()


def _safe_upload_name(filename: str) -> str:
    name = Path(filename).name or "upload"
    return "".join(char if char.isalnum() or char in ".-_" else "-" for char in name)


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]


def _safe_message(exc: Exception) -> str:
    message = str(exc)
    for fragment in ("sk-", "Bearer", "authorization", "cookie", "access_token"):
        message = message.replace(fragment, "<redacted>")
    return message[:800]

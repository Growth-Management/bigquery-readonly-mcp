from collections.abc import Callable
from typing import Any
import time

import httpx
from google.auth.credentials import Credentials
from google.cloud import bigquery

from app.audit import audit_log
from app.config import Settings
from app.sessions import UserSession
from app.sql_guard import SqlValidationError, validate_readonly_sql

BIGQUERY_API = "https://bigquery.googleapis.com/bigquery/v2"


class ProjectNotAllowedError(ValueError):
    pass


class UserNotAllowedError(ValueError):
    pass


class AccessTokenCredentials(Credentials):
    def __init__(self, token: str) -> None:
        super().__init__()
        self.token = token

    @property
    def expired(self) -> bool:
        return False

    @property
    def valid(self) -> bool:
        return bool(self.token)

    def refresh(self, request: Any) -> None:
        return None


def _client(session: UserSession, project_id: str) -> bigquery.Client:
    return bigquery.Client(
        project=project_id,
        credentials=AccessTokenCredentials(session.access_token),
    )


def _project(args: dict[str, Any], settings: Settings) -> str:
    return str(args.get("project_id") or settings.default_project_id)


def _enforce_user_allowed(session: UserSession, settings: Settings) -> None:
    allowed_user_emails = settings.allowed_user_email_set
    user_email = session.email.lower()
    if allowed_user_emails and user_email not in allowed_user_emails:
        raise UserNotAllowedError(f"User is not allowed by ALLOWED_USER_EMAILS: {session.email}")


def _enforce_project_allowed(project_id: str, settings: Settings) -> None:
    allowed_project_ids = settings.allowed_project_id_set
    if allowed_project_ids and project_id not in allowed_project_ids:
        allowed = ", ".join(sorted(allowed_project_ids))
        raise ProjectNotAllowedError(f"Project is not allowed by ALLOWED_PROJECT_IDS: {project_id}. Allowed projects: {allowed}")


def _query_headers(session: UserSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {session.access_token}", "Content-Type": "application/json"}


def _query_payload(sql: str, settings: Settings, *, dry_run: bool, max_results: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": sql,
        "dryRun": dry_run,
        "useLegacySql": False,
        "useQueryCache": False,
        "maximumBytesBilled": str(settings.maximum_bytes_billed),
        "timeoutMs": settings.query_timeout_seconds * 1000,
        "jobTimeoutMs": str(settings.query_timeout_seconds * 1000),
    }
    if max_results is not None:
        payload["maxResults"] = max_results
    return payload


def _post_query(session: UserSession, project_id: str, payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.query_timeout_seconds + 10)
    response = httpx.post(
        f"{BIGQUERY_API}/projects/{project_id}/queries",
        headers=_query_headers(session),
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def _wait_for_query(session: UserSession, query_response: dict[str, Any], settings: Settings, max_results: int) -> dict[str, Any]:
    if query_response.get("jobComplete", True):
        return query_response

    job_ref = query_response.get("jobReference") or {}
    project_id = job_ref.get("projectId")
    job_id = job_ref.get("jobId")
    if not project_id or not job_id:
        raise RuntimeError("BigQuery query did not complete and did not return a job reference")

    deadline = time.monotonic() + settings.query_timeout_seconds
    timeout = httpx.Timeout(settings.query_timeout_seconds + 10)
    params: dict[str, Any] = {"maxResults": max_results, "timeoutMs": 1000}
    if job_ref.get("location"):
        params["location"] = job_ref["location"]

    while time.monotonic() < deadline:
        response = httpx.get(
            f"{BIGQUERY_API}/projects/{project_id}/queries/{job_id}",
            headers=_query_headers(session),
            params=params,
            timeout=timeout,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("jobComplete", False):
            return result
        time.sleep(1)

    raise TimeoutError("BigQuery query did not complete within the configured timeout")


def _decode_field_value(field: dict[str, Any], value: Any) -> Any:
    if value is None:
        return None
    if field.get("mode") == "REPEATED" and isinstance(value, list):
        return [_decode_field_value({**field, "mode": "NULLABLE"}, item.get("v") if isinstance(item, dict) else item) for item in value]
    if field.get("type") == "RECORD" and isinstance(value, dict):
        child_fields = field.get("fields") or []
        child_values = value.get("f") or []
        return {
            child_field.get("name", str(index)): _decode_field_value(child_field, child_value.get("v"))
            for index, (child_field, child_value) in enumerate(zip(child_fields, child_values, strict=False))
        }
    return value


def _rows_to_dicts(query_response: dict[str, Any]) -> list[dict[str, Any]]:
    fields = ((query_response.get("schema") or {}).get("fields")) or []
    rows = query_response.get("rows") or []
    row_values: list[dict[str, Any]] = []
    for row in rows:
        values = row.get("f") or []
        row_values.append(
            {
                field.get("name", str(index)): _decode_field_value(field, value.get("v"))
                for index, (field, value) in enumerate(zip(fields, values, strict=False))
            }
        )
    return row_values


def list_projects(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    client = _client(session, project_id)
    projects = [{"project_id": project.project_id, "friendly_name": project.friendly_name} for project in client.list_projects()]
    allowed_project_ids = settings.allowed_project_id_set
    if allowed_project_ids:
        projects = [project for project in projects if project["project_id"] in allowed_project_ids]
    return {"projects": projects}


def list_datasets(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    client = _client(session, project_id)
    datasets = [{"dataset_id": dataset.dataset_id, "full_dataset_id": dataset.full_dataset_id} for dataset in client.list_datasets(project=project_id)]
    return {"project_id": project_id, "datasets": datasets}


def list_tables(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    dataset_id = str(args["dataset_id"])
    client = _client(session, project_id)
    dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
    tables = [
        {"table_id": table.table_id, "table_type": table.table_type, "full_table_id": table.full_table_id}
        for table in client.list_tables(dataset_ref)
    ]
    return {"project_id": project_id, "dataset_id": dataset_id, "tables": tables}


def get_table_schema(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    dataset_id = str(args["dataset_id"])
    table_id = str(args["table_id"])
    client = _client(session, project_id)
    table = client.get_table(bigquery.TableReference(bigquery.DatasetReference(project_id, dataset_id), table_id))
    schema = [
        {"name": field.name, "type": field.field_type, "mode": field.mode, "description": field.description}
        for field in table.schema
    ]
    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "table_id": table_id,
        "num_rows": table.num_rows,
        "schema": schema,
    }


def dry_run_query(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    sql = str(args["sql"])
    validate_readonly_sql(sql)
    query_response = _post_query(session, project_id, _query_payload(sql, settings, dry_run=True), settings)
    return {
        "project_id": project_id,
        "total_bytes_processed": int(query_response.get("totalBytesProcessed") or 0),
        "maximum_bytes_billed": settings.maximum_bytes_billed,
    }


def run_readonly_query(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    sql = str(args["sql"])
    validate_readonly_sql(sql)
    max_results = min(int(args.get("max_results") or settings.max_results), settings.max_results)
    query_response = _post_query(session, project_id, _query_payload(sql, settings, dry_run=False, max_results=max_results), settings)
    query_response = _wait_for_query(session, query_response, settings, max_results)
    row_values = _rows_to_dicts(query_response)
    return {
        "project_id": project_id,
        "total_bytes_processed": int(query_response.get("totalBytesProcessed") or 0),
        "total_bytes_billed": int(query_response.get("totalBytesBilled") or 0),
        "rows": row_values,
        "row_count": int(query_response.get("totalRows") or len(row_values)),
        "returned_rows": len(row_values),
    }


ToolHandler = Callable[[UserSession, dict[str, Any], Settings], dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "list_projects": list_projects,
    "list_datasets": list_datasets,
    "list_tables": list_tables,
    "get_table_schema": get_table_schema,
    "dry_run_query": dry_run_query,
    "run_readonly_query": run_readonly_query,
}


def call_tool(name: str, session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    handler = TOOL_HANDLERS[name]
    project_id = str(args.get("project_id") or settings.default_project_id)
    try:
        _enforce_user_allowed(session, settings)
        _enforce_project_allowed(project_id, settings)
        result = handler(session, args, settings)
        audit_log(
            user_email=session.email,
            tool=name,
            project_id=str(project_id),
            dataset=args.get("dataset_id"),
            table=args.get("table_id"),
            bytes_processed=result.get("total_bytes_processed"),
            success=True,
        )
        return result
    except SqlValidationError as exc:
        audit_log(user_email=session.email, tool=name, project_id=str(project_id), success=False, error=str(exc))
        raise
    except UserNotAllowedError as exc:
        audit_log(
            user_email=session.email,
            tool=name,
            project_id=str(project_id),
            dataset=args.get("dataset_id"),
            table=args.get("table_id"),
            success=False,
            error=str(exc),
            extra={"rejection_reason": "user_not_allowed"},
        )
        raise
    except ProjectNotAllowedError as exc:
        audit_log(
            user_email=session.email,
            tool=name,
            project_id=str(project_id),
            dataset=args.get("dataset_id"),
            table=args.get("table_id"),
            success=False,
            error=str(exc),
            extra={"rejection_reason": "project_not_allowed"},
        )
        raise
    except Exception as exc:
        audit_log(
            user_email=session.email,
            tool=name,
            project_id=str(project_id),
            dataset=args.get("dataset_id"),
            table=args.get("table_id"),
            success=False,
            error=str(exc),
        )
        raise

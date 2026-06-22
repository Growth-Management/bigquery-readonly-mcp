from collections.abc import Callable
from typing import Any
import json
import time

import httpx
from google.api_core import exceptions as google_exceptions
from google.auth.credentials import Credentials
from google.cloud import bigquery

from app.audit import audit_log
from app.config import Settings
from app.sessions import UserSession
from app.sql_guard import SqlValidationError, validate_readonly_sql

BIGQUERY_API = "https://bigquery.googleapis.com/bigquery/v2"

REJECTION_PROJECT_NOT_ALLOWED = "project_not_allowed"
REJECTION_DATASET_NOT_ALLOWED = "dataset_not_allowed"
REJECTION_USER_NOT_ALLOWED = "user_not_allowed"
REJECTION_SQL_NOT_ALLOWED = "sql_not_allowed"
REJECTION_BIGQUERY_IAM_DENIED = "bigquery_iam_denied"
REJECTION_BIGQUERY_API_ERROR = "bigquery_api_error"
REJECTION_EXECUTION_ERROR = "execution_error"


class ProjectNotAllowedError(ValueError):
    pass


class DatasetNotAllowedError(ValueError):
    pass


class UserNotAllowedError(ValueError):
    pass


class BigQueryApiError(RuntimeError):
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self.payload = payload
        super().__init__(json.dumps(payload, ensure_ascii=False, sort_keys=True))


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


def _dataset_key(project_id: str, dataset_id: str) -> str:
    return f"{project_id}:{dataset_id}"


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


def _enforce_dataset_allowed(project_id: str, dataset_id: str, settings: Settings) -> None:
    allowed_dataset_ids = settings.allowed_dataset_id_set
    dataset_key = _dataset_key(project_id, dataset_id)
    if allowed_dataset_ids and dataset_key not in allowed_dataset_ids:
        allowed = ", ".join(sorted(allowed_dataset_ids))
        raise DatasetNotAllowedError(f"Dataset is not allowed by ALLOWED_DATASET_IDS: {dataset_key}. Allowed datasets: {allowed}")


def _query_headers(session: UserSession) -> dict[str, str]:
    return {"Authorization": f"Bearer {session.access_token}", "Content-Type": "application/json"}


def _bounded_max_results(args: dict[str, Any], settings: Settings) -> int:
    requested = int(args.get("max_results") or settings.max_results)
    return max(1, min(requested, settings.max_results))


def _maximum_bytes_billed(args: dict[str, Any], settings: Settings) -> int:
    return int(args.get("maximum_bytes_billed") or settings.maximum_bytes_billed)


def _query_payload(
    sql: str,
    settings: Settings,
    *,
    dry_run: bool,
    max_results: int | None = None,
    maximum_bytes_billed: int | None = None,
    use_query_cache: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": sql,
        "dryRun": dry_run,
        "useLegacySql": False,
        "useQueryCache": bool(use_query_cache) if use_query_cache is not None else False,
        "maximumBytesBilled": str(maximum_bytes_billed or settings.maximum_bytes_billed),
        "timeoutMs": settings.query_timeout_seconds * 1000,
        "jobTimeoutMs": str(settings.query_timeout_seconds * 1000),
    }
    if max_results is not None:
        payload["maxResults"] = max_results
    return payload


def _job_labels(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("job_labels must be an object")
    return {str(key): str(label_value) for key, label_value in value.items() if label_value is not None}


def _api_error_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {"message": response.text}
    error = body.get("error") if isinstance(body, dict) else None
    return {
        "status_code": response.status_code,
        "errorResult": error if isinstance(error, dict) else body,
        "errors": error.get("errors", []) if isinstance(error, dict) else [],
    }


def _raise_for_status_with_body(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise BigQueryApiError(response.status_code, _api_error_payload(response))


def _request_json(
    method: str,
    url: str,
    session: UserSession,
    settings: Settings,
    *,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeout = httpx.Timeout(settings.query_timeout_seconds + 10)
    response = httpx.request(
        method,
        url,
        headers=_query_headers(session),
        params=params,
        json=json_payload,
        timeout=timeout,
    )
    _raise_for_status_with_body(response)
    return response.json()


def _post_query(session: UserSession, project_id: str, payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return _request_json("POST", f"{BIGQUERY_API}/projects/{project_id}/queries", session, settings, json_payload=payload)


def _wait_for_query(session: UserSession, query_response: dict[str, Any], settings: Settings, max_results: int) -> dict[str, Any]:
    if query_response.get("jobComplete", True):
        return query_response

    job_ref = query_response.get("jobReference") or {}
    project_id = job_ref.get("projectId")
    job_id = job_ref.get("jobId")
    if not project_id or not job_id:
        raise RuntimeError("BigQuery query did not complete and did not return a job reference")

    deadline = time.monotonic() + settings.query_timeout_seconds
    params: dict[str, Any] = {"maxResults": max_results, "timeoutMs": 1000}
    if job_ref.get("location"):
        params["location"] = job_ref["location"]

    while time.monotonic() < deadline:
        result = _request_json(
            "GET",
            f"{BIGQUERY_API}/projects/{project_id}/queries/{job_id}",
            session,
            settings,
            params=params,
        )
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


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    job_ref = job.get("jobReference") or {}
    status = job.get("status") or {}
    statistics = job.get("statistics") or {}
    query_stats = statistics.get("query") or {}
    return {
        "job_id": job_ref.get("jobId"),
        "project_id": job_ref.get("projectId"),
        "location": job_ref.get("location"),
        "state": status.get("state"),
        "created_at": statistics.get("creationTime"),
        "started_at": statistics.get("startTime"),
        "ended_at": statistics.get("endTime"),
        "total_bytes_processed": int(query_stats.get("totalBytesProcessed") or 0),
        "total_bytes_billed": int(query_stats.get("totalBytesBilled") or 0),
        "cache_hit": query_stats.get("cacheHit"),
        "errorResult": status.get("errorResult"),
        "errors": status.get("errors", []),
    }


def _job_result_params(args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    params: dict[str, Any] = {
        "maxResults": _bounded_max_results(args, settings),
        "timeoutMs": 0,
    }
    if args.get("page_token"):
        params["pageToken"] = str(args["page_token"])
    if args.get("location"):
        params["location"] = str(args["location"])
    return params


def _job_location_params(args: dict[str, Any]) -> dict[str, Any]:
    return {"location": str(args["location"])} if args.get("location") else {}


def _is_bigquery_iam_denied(exc: Exception) -> bool:
    if isinstance(exc, BigQueryApiError):
        return exc.status_code == 403
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 403
    if isinstance(exc, google_exceptions.Forbidden):
        return True
    return False


def _is_bigquery_api_error(exc: Exception) -> bool:
    return isinstance(exc, (BigQueryApiError, httpx.HTTPError, google_exceptions.GoogleAPICallError))


def _failure_audit_extra(rejection_reason: str) -> dict[str, str]:
    return {"rejection_reason": rejection_reason}


def _audit_failure(
    *,
    session: UserSession,
    tool: str,
    project_id: str,
    args: dict[str, Any],
    error: Exception,
    rejection_reason: str,
) -> None:
    audit_log(
        user_email=session.email,
        tool=tool,
        project_id=str(project_id),
        dataset=args.get("dataset_id"),
        table=args.get("table_id"),
        success=False,
        error=str(error),
        extra=_failure_audit_extra(rejection_reason),
    )


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
    allowed_dataset_ids = settings.allowed_dataset_id_set
    datasets = [
        {"dataset_id": dataset.dataset_id, "full_dataset_id": dataset.full_dataset_id}
        for dataset in client.list_datasets(project=project_id)
        if not allowed_dataset_ids or _dataset_key(project_id, dataset.dataset_id) in allowed_dataset_ids
    ]
    return {"project_id": project_id, "datasets": datasets}


def list_tables(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    dataset_id = str(args["dataset_id"])
    _enforce_dataset_allowed(project_id, dataset_id, settings)
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
    _enforce_dataset_allowed(project_id, dataset_id, settings)
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
    maximum_bytes_billed = _maximum_bytes_billed(args, settings)
    query_response = _post_query(
        session,
        project_id,
        _query_payload(sql, settings, dry_run=True, maximum_bytes_billed=maximum_bytes_billed),
        settings,
    )
    return {
        "project_id": project_id,
        "total_bytes_processed": int(query_response.get("totalBytesProcessed") or 0),
        "maximum_bytes_billed": maximum_bytes_billed,
    }


def run_readonly_query(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    sql = str(args["sql"])
    validate_readonly_sql(sql)
    max_results = _bounded_max_results(args, settings)
    query_response = _post_query(
        session,
        project_id,
        _query_payload(sql, settings, dry_run=False, max_results=max_results),
        settings,
    )
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


def start_readonly_query_job(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    sql = str(args["sql"])
    validate_readonly_sql(sql)
    maximum_bytes_billed = _maximum_bytes_billed(args, settings)
    use_query_cache = args.get("use_query_cache")

    if bool(args.get("dry_run", False)):
        query_response = _post_query(
            session,
            project_id,
            _query_payload(
                sql,
                settings,
                dry_run=True,
                maximum_bytes_billed=maximum_bytes_billed,
                use_query_cache=bool(use_query_cache) if use_query_cache is not None else None,
            ),
            settings,
        )
        return {
            "dry_run": True,
            "project_id": project_id,
            "location": args.get("location"),
            "state": "DONE",
            "total_bytes_processed": int(query_response.get("totalBytesProcessed") or 0),
            "maximum_bytes_billed": maximum_bytes_billed,
        }

    job_reference: dict[str, Any] = {"projectId": project_id}
    if args.get("location"):
        job_reference["location"] = str(args["location"])
    query_config: dict[str, Any] = {
        "query": sql,
        "useLegacySql": False,
        "maximumBytesBilled": str(maximum_bytes_billed),
    }
    if use_query_cache is not None:
        query_config["useQueryCache"] = bool(use_query_cache)
    payload: dict[str, Any] = {
        "jobReference": job_reference,
        "configuration": {"query": query_config},
    }
    labels = _job_labels(args.get("job_labels"))
    if labels:
        payload["configuration"]["labels"] = labels

    job = _request_json("POST", f"{BIGQUERY_API}/projects/{project_id}/jobs", session, settings, json_payload=payload)
    result = _job_summary(job)
    result["maximum_bytes_billed"] = maximum_bytes_billed
    return result


def get_query_job_status(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    job = _request_json(
        "GET",
        f"{BIGQUERY_API}/projects/{project_id}/jobs/{args['job_id']}",
        session,
        settings,
        params=_job_location_params(args),
    )
    return _job_summary(job)


def fetch_query_job_results(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    query_response = _request_json(
        "GET",
        f"{BIGQUERY_API}/projects/{project_id}/queries/{args['job_id']}",
        session,
        settings,
        params=_job_result_params(args, settings),
    )
    row_values = _rows_to_dicts(query_response)
    return {
        "project_id": project_id,
        "job_id": str(args["job_id"]),
        "schema": (query_response.get("schema") or {}).get("fields", []),
        "rows": row_values,
        "next_page_token": query_response.get("pageToken"),
        "total_rows": int(query_response.get("totalRows") or len(row_values)),
        "returned_rows": len(row_values),
        "job_complete": bool(query_response.get("jobComplete", False)),
        "errorResult": query_response.get("errorResult"),
        "errors": query_response.get("errors", []),
    }


def cancel_query_job(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    response = _request_json(
        "POST",
        f"{BIGQUERY_API}/projects/{project_id}/jobs/{args['job_id']}/cancel",
        session,
        settings,
        params=_job_location_params(args),
    )
    job = response.get("job") or {}
    result = _job_summary(job)
    result["cancelled"] = True
    return result


ToolHandler = Callable[[UserSession, dict[str, Any], Settings], dict[str, Any]]

TOOL_HANDLERS: dict[str, ToolHandler] = {
    "list_projects": list_projects,
    "list_datasets": list_datasets,
    "list_tables": list_tables,
    "get_table_schema": get_table_schema,
    "dry_run_query": dry_run_query,
    "run_readonly_query": run_readonly_query,
    "start_readonly_query_job": start_readonly_query_job,
    "get_query_job_status": get_query_job_status,
    "fetch_query_job_results": fetch_query_job_results,
    "cancel_query_job": cancel_query_job,
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
            extra={"job_id": result.get("job_id")} if result.get("job_id") else None,
        )
        return result
    except SqlValidationError as exc:
        _audit_failure(
            session=session,
            tool=name,
            project_id=project_id,
            args=args,
            error=exc,
            rejection_reason=REJECTION_SQL_NOT_ALLOWED,
        )
        raise
    except UserNotAllowedError as exc:
        _audit_failure(
            session=session,
            tool=name,
            project_id=project_id,
            args=args,
            error=exc,
            rejection_reason=REJECTION_USER_NOT_ALLOWED,
        )
        raise
    except ProjectNotAllowedError as exc:
        _audit_failure(
            session=session,
            tool=name,
            project_id=project_id,
            args=args,
            error=exc,
            rejection_reason=REJECTION_PROJECT_NOT_ALLOWED,
        )
        raise
    except DatasetNotAllowedError as exc:
        _audit_failure(
            session=session,
            tool=name,
            project_id=project_id,
            args=args,
            error=exc,
            rejection_reason=REJECTION_DATASET_NOT_ALLOWED,
        )
        raise
    except Exception as exc:
        if _is_bigquery_iam_denied(exc):
            rejection_reason = REJECTION_BIGQUERY_IAM_DENIED
        elif _is_bigquery_api_error(exc):
            rejection_reason = REJECTION_BIGQUERY_API_ERROR
        else:
            rejection_reason = REJECTION_EXECUTION_ERROR
        _audit_failure(
            session=session,
            tool=name,
            project_id=project_id,
            args=args,
            error=exc,
            rejection_reason=rejection_reason,
        )
        raise

from collections.abc import Callable
from typing import Any

from google.auth.credentials import Credentials
from google.cloud import bigquery

from app.audit import audit_log
from app.config import Settings
from app.sessions import UserSession
from app.sql_guard import SqlValidationError, validate_readonly_sql


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


def list_projects(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    client = _client(session, project_id)
    projects = [{"project_id": project.project_id, "friendly_name": project.friendly_name} for project in client.list_projects()]
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
    client = _client(session, project_id)
    job_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        maximum_bytes_billed=settings.maximum_bytes_billed,
    )
    job = client.query(sql, job_config=job_config, timeout=settings.query_timeout_seconds)
    return {
        "project_id": project_id,
        "total_bytes_processed": job.total_bytes_processed,
        "maximum_bytes_billed": settings.maximum_bytes_billed,
    }


def run_readonly_query(session: UserSession, args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    project_id = _project(args, settings)
    sql = str(args["sql"])
    validate_readonly_sql(sql)
    max_results = min(int(args.get("max_results") or settings.max_results), settings.max_results)
    client = _client(session, project_id)
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=settings.maximum_bytes_billed)
    job = client.query(sql, job_config=job_config, timeout=settings.query_timeout_seconds)
    rows = job.result(timeout=settings.query_timeout_seconds, max_results=max_results)
    row_values = [dict(row.items()) for row in rows]
    return {
        "project_id": project_id,
        "total_bytes_processed": job.total_bytes_processed,
        "rows": row_values,
        "row_count": rows.total_rows,
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
    project_id = args.get("project_id") or settings.default_project_id
    try:
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

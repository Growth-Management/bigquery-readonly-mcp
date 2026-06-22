import json
from typing import Any

from app.bigquery_tools import TOOL_HANDLERS, call_tool
from app.config import Settings
from app.sessions import UserSession


TOOLS = [
    {
        "name": "list_projects",
        "description": "List BigQuery projects visible to the authenticated user.",
        "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}},
    },
    {
        "name": "list_datasets",
        "description": "List datasets in a BigQuery project.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
        },
    },
    {
        "name": "list_tables",
        "description": "List tables in a BigQuery dataset.",
        "inputSchema": {
            "type": "object",
            "required": ["dataset_id"],
            "properties": {"project_id": {"type": "string"}, "dataset_id": {"type": "string"}},
        },
    },
    {
        "name": "get_table_schema",
        "description": "Get BigQuery table schema metadata.",
        "inputSchema": {
            "type": "object",
            "required": ["dataset_id", "table_id"],
            "properties": {
                "project_id": {"type": "string"},
                "dataset_id": {"type": "string"},
                "table_id": {"type": "string"},
            },
        },
    },
    {
        "name": "dry_run_query",
        "description": "Dry run a readonly SELECT/WITH query and return estimated bytes processed.",
        "inputSchema": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "project_id": {"type": "string"},
                "sql": {"type": "string"},
                "maximum_bytes_billed": {"type": "integer", "minimum": 1},
            },
        },
    },
    {
        "name": "run_readonly_query",
        "description": "Run a readonly SELECT/WITH query with maximumBytesBilled and result limits.",
        "inputSchema": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "project_id": {"type": "string"},
                "sql": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        },
    },
    {
        "name": "start_readonly_query_job",
        "description": (
            "Start a BigQuery Job API query for a readonly SELECT/WITH query. "
            "Use this for longer validation queries that should run as jobs instead of the synchronous query endpoint. "
            "When dry_run=true, returns a dry-run estimate without creating a job."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["sql"],
            "properties": {
                "project_id": {"type": "string"},
                "sql": {"type": "string"},
                "location": {"type": "string"},
                "maximum_bytes_billed": {"type": "integer", "minimum": 1},
                "job_labels": {"type": "object", "additionalProperties": {"type": "string"}},
                "dry_run": {"type": "boolean", "default": False},
                "use_query_cache": {"type": "boolean"},
            },
        },
    },
    {
        "name": "get_query_job_status",
        "description": "Get BigQuery query job state, timings, bytes, cache hit, errorResult, and errors.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "project_id": {"type": "string"},
                "job_id": {"type": "string"},
                "location": {"type": "string"},
            },
        },
    },
    {
        "name": "fetch_query_job_results",
        "description": "Fetch one bounded page of BigQuery query job results with schema, rows, and next_page_token.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "project_id": {"type": "string"},
                "job_id": {"type": "string"},
                "location": {"type": "string"},
                "page_token": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
        },
    },
    {
        "name": "cancel_query_job",
        "description": "Cancel a BigQuery query job started by the authenticated user's permissions.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "project_id": {"type": "string"},
                "job_id": {"type": "string"},
                "location": {"type": "string"},
            },
        },
    },
]


def handle_json_rpc(payload: dict[str, Any], session: UserSession, settings: Settings) -> dict[str, Any]:
    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "bigquery-readonly-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            if name not in TOOL_HANDLERS:
                raise ValueError(f"Unknown tool: {name}")
            tool_result = call_tool(name, session, params.get("arguments") or {}, settings)
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(tool_result, ensure_ascii=False, sort_keys=True),
                    }
                ]
            }
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

from app.bigquery_tools import _job_summary, _single_referenced_table, _success_audit_extra


def test_job_summary_includes_referenced_tables() -> None:
    job = {
        "jobReference": {
            "projectId": "jumpplus-4a5f4",
            "jobId": "job_123",
            "location": "asia-northeast1",
        },
        "status": {"state": "DONE"},
        "statistics": {
            "query": {
                "totalBytesProcessed": "12345",
                "totalBytesBilled": "10485760",
                "cacheHit": False,
                "referencedTables": [
                    {
                        "projectId": "jumpplus-4a5f4",
                        "datasetId": "analytics",
                        "tableId": "events",
                    },
                    {
                        "projectId": "jumpplus-4a5f4",
                        "datasetId": "master",
                        "tableId": "users",
                    },
                ],
            }
        },
    }

    summary = _job_summary(job)

    assert summary["referenced_table_count"] == 2
    assert summary["referenced_tables"] == [
        {
            "project_id": "jumpplus-4a5f4",
            "dataset_id": "analytics",
            "table_id": "events",
            "full_table_id": "jumpplus-4a5f4.analytics.events",
        },
        {
            "project_id": "jumpplus-4a5f4",
            "dataset_id": "master",
            "table_id": "users",
            "full_table_id": "jumpplus-4a5f4.master.users",
        },
    ]


def test_job_summary_skips_incomplete_referenced_tables() -> None:
    job = {
        "statistics": {
            "query": {
                "referencedTables": [
                    {"projectId": "jumpplus-4a5f4"},
                    {
                        "projectId": "jumpplus-4a5f4",
                        "datasetId": "analytics",
                        "tableId": "events",
                    },
                ]
            }
        }
    }

    summary = _job_summary(job)

    assert summary["referenced_table_count"] == 1
    assert summary["referenced_tables"][0]["full_table_id"] == "jumpplus-4a5f4.analytics.events"


def test_single_referenced_table_only_returns_single_table() -> None:
    single_table_result = {
        "referenced_tables": [
            {
                "project_id": "jumpplus-4a5f4",
                "dataset_id": "analytics",
                "table_id": "events",
                "full_table_id": "jumpplus-4a5f4.analytics.events",
            }
        ]
    }
    multi_table_result = {
        "referenced_tables": [
            {"dataset_id": "analytics", "table_id": "events"},
            {"dataset_id": "master", "table_id": "users"},
        ]
    }

    assert _single_referenced_table(single_table_result) == single_table_result["referenced_tables"][0]
    assert _single_referenced_table(multi_table_result) is None


def test_success_audit_extra_includes_job_and_referenced_tables() -> None:
    result = {
        "job_id": "job_123",
        "referenced_tables": [
            {
                "project_id": "jumpplus-4a5f4",
                "dataset_id": "analytics",
                "table_id": "events",
                "full_table_id": "jumpplus-4a5f4.analytics.events",
            }
        ],
    }

    assert _success_audit_extra(result) == {
        "job_id": "job_123",
        "referenced_tables": result["referenced_tables"],
        "referenced_table_count": 1,
    }

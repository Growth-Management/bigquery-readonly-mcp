import pytest

from app.sql_guard import SqlValidationError, validate_readonly_sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH source AS (SELECT 1 AS value) SELECT value FROM source",
        "SELECT 'DELETE is text' AS label",
        "SELECT * FROM `ice-sh.dataset.create`",
    ],
)
def test_allows_readonly_queries(sql: str) -> None:
    validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO dataset.table VALUES (1)",
        "UPDATE dataset.table SET value = 1",
        "DELETE FROM dataset.table WHERE true",
        "MERGE dataset.table T USING dataset.source S ON T.id = S.id WHEN MATCHED THEN UPDATE SET value = S.value",
        "CREATE TABLE dataset.table AS SELECT 1",
        "DROP TABLE dataset.table",
        "ALTER TABLE dataset.table ADD COLUMN value STRING",
        "TRUNCATE TABLE dataset.table",
        "EXPORT DATA OPTIONS(uri='gs://bucket/file.csv') AS SELECT 1",
        "LOAD DATA INTO dataset.table FROM FILES(uri='gs://bucket/file.csv')",
        "GRANT `roles/bigquery.dataViewer` ON SCHEMA dataset TO 'user:a@example.com'",
        "REVOKE `roles/bigquery.dataViewer` ON SCHEMA dataset FROM 'user:a@example.com'",
        "CALL dataset.proc()",
        "SELECT 1; SELECT 2",
    ],
)
def test_rejects_non_readonly_or_multi_statement_queries(sql: str) -> None:
    with pytest.raises(SqlValidationError):
        validate_readonly_sql(sql)

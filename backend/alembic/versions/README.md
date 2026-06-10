# Alembic migration chain (PostgreSQL)

| Revision | File | Scope |
|----------|------|--------|
| `20260528_0001` | `20260528_0001_initial_postgresql_schema.py` | Initial schema |
| `20260610_0002` | `20260610_0002_wps_standard_query_records.py` | WPS standard query records |
| `20260610_0003` | `20260610_0003_data_governance_schema.py` | UrlSource / TrustedSource governance fields; `source_governance_runs`, `source_record_candidates`, `governance_decisions`, `process_audit_logs` |
| `20260610_0004` | `20260610_0004_governance_decision_phase3.py` | StandardResource decision fields; Alert dedupe; governance_decisions & audit log extensions |
| `20260610_0005` | `20260610_0005_ocr_download_file_objects.py` | `file_objects`, `ocr_download_tasks`; DocumentVersion `file_object_id`, `original_file_name` |

Apply all governance migrations:

```bash
cd backend
alembic upgrade head
alembic current
```

Expected head: `20260610_0005`.

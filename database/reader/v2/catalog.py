"""Additive writer for reader-v2 catalog metadata without mutating released v1 metadata."""
import hashlib
import json


def save_v2_catalog_field(cur, field, metadata, body, contract_version):
    """Write only to the additive, source-versioned v2 catalog."""
    body = {**body, "contract_version": contract_version, "field_id": field,
            "dataset_id": metadata["dataset_id"], "sourceCode": metadata["source_code"],
            "sourceRelease": metadata["release"], "candidate_status": "local_review_not_admitted"}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    cur.execute("""INSERT INTO usa_atlas.reader_v2_catalog_field
        (catalog_field_id,source_release,dataset_id,catalog_label,source_code,contract_version,contract,contract_sha256,candidate_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'local_review')
        ON CONFLICT (catalog_field_id,source_release) DO UPDATE SET
          dataset_id=EXCLUDED.dataset_id,catalog_label=EXCLUDED.catalog_label,
          source_code=EXCLUDED.source_code,contract_version=EXCLUDED.contract_version,
          contract=EXCLUDED.contract,contract_sha256=EXCLUDED.contract_sha256,
          candidate_status=EXCLUDED.candidate_status""",
        (field, metadata["release"], metadata["dataset_id"], metadata["label"],
         metadata["source_code"], contract_version, json.dumps(body, sort_keys=True), digest))

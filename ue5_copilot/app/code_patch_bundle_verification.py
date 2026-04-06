from __future__ import annotations

from app.code_patch_drafter import hash_content


def build_code_patch_bundle_verification_token(requested_files: list[dict]) -> str:
    normalized_parts = []
    for item in requested_files:
        normalized_parts.append(
            "|".join(
                [
                    str(item.get("target_path", "")).strip(),
                    str(item.get("original_content_hash", "")).strip(),
                    hash_content(str(item.get("updated_content", ""))),
                ]
            )
        )
    return hash_content("\n".join(sorted(normalized_parts)))


def build_code_patch_bundle_file_checksums(requested_files: list[dict]) -> list[dict[str, str]]:
    return [
        {
            "target_path": str(item.get("target_path", "")).strip(),
            "original_content_hash": str(item.get("original_content_hash", "")).strip(),
            "updated_content_hash": hash_content(str(item.get("updated_content", ""))),
        }
        for item in requested_files
    ]


def build_agent_session_approval_token(*, task_id: str, verification_token: str, approval_nonce: str) -> str:
    normalized_parts = [
        str(task_id or "").strip(),
        str(verification_token or "").strip(),
        str(approval_nonce or "").strip(),
    ]
    return hash_content("|".join(normalized_parts))


def build_agent_session_dry_run_receipt_token(
    *,
    task_id: str,
    approval_token: str,
    verification_token: str,
    receipt_nonce: str,
) -> str:
    normalized_parts = [
        str(task_id or "").strip(),
        str(approval_token or "").strip(),
        str(verification_token or "").strip(),
        str(receipt_nonce or "").strip(),
    ]
    return hash_content("|".join(normalized_parts))

"""Document file classification decision constants."""

from __future__ import annotations

DECISION_DUPLICATE_EXISTING = "duplicate_existing"
DECISION_AUTO_CONFIRM = "auto_confirm"
DECISION_AUTO_CLASSIFY = "auto_classify"
DECISION_LINK_EXISTING = "link_existing"
DECISION_NEW_VERSION = "new_version"
DECISION_QUARANTINE = "quarantine"
DECISION_CONFLICT_BLOCK = "conflict_block"
DECISION_MANUAL_REVIEW = "manual_review"

ISOLATED_INGEST_DECISIONS = frozenset(
    {
        DECISION_QUARANTINE,
        DECISION_CONFLICT_BLOCK,
    }
)

FORMAL_INGEST_DECISIONS = frozenset(
    {
        DECISION_AUTO_CONFIRM,
        DECISION_AUTO_CLASSIFY,
        DECISION_LINK_EXISTING,
        DECISION_NEW_VERSION,
    }
)

# Map new decisions to legacy local intake task decisions
LEGACY_INTAKE_DECISION_MAP = {
    DECISION_DUPLICATE_EXISTING: "duplicate_ignore",
    DECISION_AUTO_CONFIRM: "create_document",
    DECISION_AUTO_CLASSIFY: "create_document",
    DECISION_LINK_EXISTING: "link_existing",
    DECISION_NEW_VERSION: "link_existing",
    DECISION_QUARANTINE: "need_review",
    DECISION_CONFLICT_BLOCK: "need_review",
    DECISION_MANUAL_REVIEW: "need_review",
}

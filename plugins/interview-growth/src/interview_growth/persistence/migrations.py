"""Small, explicit schema migrations for registry and goal databases."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

from .database import connect_database

REGISTRY_MIGRATIONS: Mapping[int, str] = {
    1: """
        CREATE TABLE goals (
            id TEXT PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            lifecycle TEXT NOT NULL CHECK (
                lifecycle IN ('configuring', 'in_progress', 'paused', 'ended', 'archived')
            ),
            database_path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE session_bindings (
            session_id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
            bound_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE idempotency_records (
            scope TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            operation TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (scope, idempotency_key)
        );

        CREATE INDEX idx_goals_lifecycle ON goals(lifecycle);
        CREATE INDEX idx_session_bindings_goal_id ON session_bindings(goal_id);
    """,
    2: """
        ALTER TABLE goals ADD COLUMN deleted_at TEXT;
        ALTER TABLE goals ADD COLUMN trash_path TEXT;

        CREATE TABLE goal_backups (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE RESTRICT,
            database_path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_goal_backups_goal ON goal_backups(goal_id, created_at);
        CREATE INDEX idx_goals_deleted ON goals(deleted_at);
    """,
}

GOAL_MIGRATIONS: Mapping[int, str] = {
    1: """
        CREATE TABLE goal_identity (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );

        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );

        CREATE TABLE idempotency_records (
            idempotency_key TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """,
    2: """
        CREATE TABLE source_materials (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('job_description', 'user_constraint')),
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE topics (
            id TEXT PRIMARY KEY,
            parent_id TEXT REFERENCES topics(id) ON DELETE RESTRICT,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
            merged_into_id TEXT REFERENCES topics(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            CHECK (id != parent_id),
            CHECK (
                (status = 'active' AND merged_into_id IS NULL)
                OR (status = 'merged' AND merged_into_id IS NOT NULL)
            )
        );

        CREATE TABLE topic_aliases (
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL UNIQUE,
            PRIMARY KEY (topic_id, normalized_alias)
        );

        CREATE TABLE capability_dimensions (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE standard_drafts (
            id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
            role_profile_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE standard_draft_sources (
            draft_id TEXT NOT NULL REFERENCES standard_drafts(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES source_materials(id) ON DELETE RESTRICT,
            PRIMARY KEY (draft_id, source_id)
        );

        CREATE TABLE standard_draft_topic_requirements (
            draft_id TEXT NOT NULL REFERENCES standard_drafts(id) ON DELETE CASCADE,
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
            required_level INTEGER NOT NULL CHECK (required_level BETWEEN 0 AND 4),
            weight REAL NOT NULL CHECK (weight > 0),
            critical INTEGER NOT NULL CHECK (critical IN (0, 1)),
            minimum_evidence_count INTEGER NOT NULL CHECK (minimum_evidence_count > 0),
            PRIMARY KEY (draft_id, topic_id)
        );

        CREATE TABLE standard_draft_capability_requirements (
            draft_id TEXT NOT NULL REFERENCES standard_drafts(id) ON DELETE CASCADE,
            capability_id TEXT NOT NULL REFERENCES capability_dimensions(id) ON DELETE RESTRICT,
            required_level INTEGER NOT NULL CHECK (required_level BETWEEN 0 AND 4),
            weight REAL NOT NULL CHECK (weight > 0),
            critical INTEGER NOT NULL CHECK (critical IN (0, 1)),
            minimum_evidence_count INTEGER NOT NULL CHECK (minimum_evidence_count > 0),
            PRIMARY KEY (draft_id, capability_id)
        );

        CREATE TABLE standard_versions (
            id TEXT PRIMARY KEY,
            version_number INTEGER NOT NULL UNIQUE CHECK (version_number > 0),
            source_draft_id TEXT NOT NULL REFERENCES standard_drafts(id) ON DELETE RESTRICT,
            source_draft_revision INTEGER NOT NULL,
            role_profile_json TEXT NOT NULL,
            approved_at TEXT NOT NULL
        );

        CREATE TABLE standard_version_sources (
            standard_version_id TEXT NOT NULL REFERENCES standard_versions(id) ON DELETE CASCADE,
            source_id TEXT NOT NULL REFERENCES source_materials(id) ON DELETE RESTRICT,
            PRIMARY KEY (standard_version_id, source_id)
        );

        CREATE TABLE standard_topic_requirements (
            standard_version_id TEXT NOT NULL REFERENCES standard_versions(id) ON DELETE CASCADE,
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
            topic_name_snapshot TEXT NOT NULL,
            required_level INTEGER NOT NULL CHECK (required_level BETWEEN 0 AND 4),
            weight REAL NOT NULL CHECK (weight > 0),
            critical INTEGER NOT NULL CHECK (critical IN (0, 1)),
            minimum_evidence_count INTEGER NOT NULL CHECK (minimum_evidence_count > 0),
            PRIMARY KEY (standard_version_id, topic_id)
        );

        CREATE TABLE standard_capability_requirements (
            standard_version_id TEXT NOT NULL REFERENCES standard_versions(id) ON DELETE CASCADE,
            capability_id TEXT NOT NULL REFERENCES capability_dimensions(id) ON DELETE RESTRICT,
            capability_name_snapshot TEXT NOT NULL,
            required_level INTEGER NOT NULL CHECK (required_level BETWEEN 0 AND 4),
            weight REAL NOT NULL CHECK (weight > 0),
            critical INTEGER NOT NULL CHECK (critical IN (0, 1)),
            minimum_evidence_count INTEGER NOT NULL CHECK (minimum_evidence_count > 0),
            PRIMARY KEY (standard_version_id, capability_id)
        );

        CREATE TABLE questions (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('pending', 'assessable', 'retired')),
            source TEXT NOT NULL,
            current_version INTEGER NOT NULL CHECK (current_version > 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            retired_at TEXT
        );

        CREATE TABLE question_versions (
            question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
            version INTEGER NOT NULL CHECK (version > 0),
            prompt TEXT NOT NULL,
            intent TEXT,
            rubric_json TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (question_id, version)
        );

        CREATE TABLE question_version_topics (
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            topic_id TEXT NOT NULL REFERENCES topics(id) ON DELETE RESTRICT,
            PRIMARY KEY (question_id, question_version, topic_id),
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE CASCADE
        );

        CREATE TABLE question_version_capabilities (
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            capability_id TEXT NOT NULL REFERENCES capability_dimensions(id) ON DELETE RESTRICT,
            PRIMARY KEY (question_id, question_version, capability_id),
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE CASCADE
        );

        CREATE INDEX idx_topics_parent ON topics(parent_id);
        CREATE INDEX idx_questions_status ON questions(status);
        CREATE INDEX idx_question_versions_prompt ON question_versions(prompt);
        CREATE INDEX idx_question_version_topics_topic ON question_version_topics(topic_id);
        CREATE INDEX idx_question_version_capabilities_capability
            ON question_version_capabilities(capability_id);
    """,
    3: """
        CREATE TABLE interview_sessions (
            id TEXT PRIMARY KEY,
            created_host_session_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('in_progress', 'paused', 'completed', 'aborted')
            ),
            standard_version_id TEXT NOT NULL
                REFERENCES standard_versions(id) ON DELETE RESTRICT,
            plan_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            paused_at TEXT,
            completed_at TEXT,
            outcome_summary TEXT
        );

        CREATE TABLE interview_items (
            id TEXT PRIMARY KEY,
            interview_id TEXT NOT NULL
                REFERENCES interview_sessions(id) ON DELETE RESTRICT,
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('main', 'followup')),
            parent_item_id TEXT REFERENCES interview_items(id) ON DELETE RESTRICT,
            trigger_attempt_id TEXT,
            sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'answered', 'evaluated', 'skipped')
            ),
            registered_at TEXT NOT NULL,
            UNIQUE (interview_id, sequence_number),
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE RESTRICT,
            FOREIGN KEY (trigger_attempt_id)
                REFERENCES attempts(id) ON DELETE RESTRICT,
            CHECK (
                (kind = 'main' AND parent_item_id IS NULL AND trigger_attempt_id IS NULL)
                OR (kind = 'followup' AND parent_item_id IS NOT NULL
                    AND trigger_attempt_id IS NOT NULL)
            )
        );

        CREATE TABLE attempts (
            id TEXT PRIMARY KEY,
            interview_id TEXT NOT NULL
                REFERENCES interview_sessions(id) ON DELETE RESTRICT,
            interview_item_id TEXT NOT NULL UNIQUE
                REFERENCES interview_items(id) ON DELETE RESTRICT,
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            answer_text TEXT NOT NULL,
            assistance_level TEXT NOT NULL CHECK (
                assistance_level IN ('independent', 'hinted', 'coached')
            ),
            recorded_at TEXT NOT NULL,
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE RESTRICT
        );

        CREATE TABLE evaluations (
            id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE RESTRICT,
            interview_id TEXT NOT NULL
                REFERENCES interview_sessions(id) ON DELETE RESTRICT,
            standard_version_id TEXT NOT NULL
                REFERENCES standard_versions(id) ON DELETE RESTRICT,
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            summary TEXT NOT NULL,
            evaluator_provenance_json TEXT NOT NULL,
            evidence_eligible INTEGER NOT NULL CHECK (evidence_eligible IN (0, 1)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE RESTRICT
        );

        CREATE TABLE dimension_evaluations (
            evaluation_id TEXT NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
            capability_id TEXT NOT NULL
                REFERENCES capability_dimensions(id) ON DELETE RESTRICT,
            level INTEGER CHECK (level BETWEEN 0 AND 4),
            evidence TEXT NOT NULL,
            gaps TEXT NOT NULL,
            improvement TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            PRIMARY KEY (evaluation_id, capability_id),
            CHECK (level IS NOT NULL OR evidence = '')
        );

        CREATE TABLE interview_checkpoints (
            id TEXT PRIMARY KEY,
            interview_id TEXT NOT NULL
                REFERENCES interview_sessions(id) ON DELETE CASCADE,
            interview_revision INTEGER NOT NULL,
            state_json TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE practice_records (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            response_text TEXT NOT NULL,
            assistance_level TEXT NOT NULL CHECK (
                assistance_level IN ('hinted', 'coached')
            ),
            coach_notes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE RESTRICT
        );

        CREATE INDEX idx_interview_sessions_status ON interview_sessions(status);
        CREATE INDEX idx_interview_items_interview
            ON interview_items(interview_id, sequence_number);
        CREATE INDEX idx_attempts_interview ON attempts(interview_id, recorded_at);
        CREATE INDEX idx_evaluations_interview ON evaluations(interview_id, created_at);
        CREATE INDEX idx_checkpoints_interview ON interview_checkpoints(interview_id, created_at);
    """,
    4: """
        CREATE TABLE evaluation_disputes (
            id TEXT PRIMARY KEY,
            evaluation_id TEXT NOT NULL UNIQUE
                REFERENCES evaluations(id) ON DELETE RESTRICT,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
            resolution TEXT CHECK (
                resolution IN ('original', 'reassessment', 'withdrawn')
            ),
            resolution_notes TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            CHECK (
                (status = 'open' AND resolution IS NULL AND resolved_at IS NULL)
                OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)
            )
        );

        CREATE TABLE evaluation_reassessments (
            id TEXT PRIMARY KEY,
            dispute_id TEXT NOT NULL UNIQUE
                REFERENCES evaluation_disputes(id) ON DELETE RESTRICT,
            summary TEXT NOT NULL,
            dimensions_json TEXT NOT NULL,
            evaluator_provenance_json TEXT NOT NULL,
            evidence_eligible INTEGER NOT NULL CHECK (evidence_eligible IN (0, 1)),
            created_at TEXT NOT NULL
        );

        CREATE TABLE training_prescriptions (
            id TEXT PRIMARY KEY,
            subject_type TEXT NOT NULL CHECK (subject_type IN ('topic', 'capability')),
            subject_id TEXT NOT NULL,
            gap_snapshot_json TEXT NOT NULL,
            action_plan TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'cancelled')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE retest_schedules (
            id TEXT PRIMARY KEY,
            prescription_id TEXT NOT NULL
                REFERENCES training_prescriptions(id) ON DELETE RESTRICT,
            question_id TEXT NOT NULL,
            question_version INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('scheduled', 'completed', 'cancelled')
            ),
            created_at TEXT NOT NULL,
            FOREIGN KEY (question_id, question_version)
                REFERENCES question_versions(question_id, version) ON DELETE RESTRICT
        );

        CREATE INDEX idx_evaluation_disputes_status
            ON evaluation_disputes(status, created_at);
        CREATE INDEX idx_training_prescriptions_status
            ON training_prescriptions(status, created_at);
        CREATE INDEX idx_retest_schedules_due
            ON retest_schedules(status, due_at);
    """,
    5: """
        CREATE TABLE real_interview_reviews (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            role_title TEXT NOT NULL,
            round_name TEXT NOT NULL,
            interviewed_at TEXT NOT NULL,
            result TEXT NOT NULL CHECK (
                result IN ('passed', 'rejected', 'pending', 'unknown')
            ),
            overall_notes TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE real_interview_question_memories (
            id TEXT PRIMARY KEY,
            review_id TEXT NOT NULL
                REFERENCES real_interview_reviews(id) ON DELETE CASCADE,
            sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
            prompt TEXT NOT NULL,
            answer_summary TEXT NOT NULL,
            interviewer_feedback TEXT NOT NULL,
            question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
            recall_confidence REAL NOT NULL CHECK (recall_confidence BETWEEN 0 AND 1),
            coverage_status TEXT NOT NULL CHECK (
                coverage_status IN ('mapped', 'blind_spot', 'unmapped')
            ),
            created_at TEXT NOT NULL,
            UNIQUE (review_id, sequence_number)
        );

        CREATE INDEX idx_real_interview_reviews_date
            ON real_interview_reviews(interviewed_at, created_at);
        CREATE INDEX idx_real_interview_memories_review
            ON real_interview_question_memories(review_id, sequence_number);
    """,
}


def _apply_migrations(
    connection: sqlite3.Connection,
    migrations: Mapping[int, str],
    database_path: Path,
) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        )
        """
    )
    connection.commit()
    applied = {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, sql in sorted(migrations.items()):
        if version in applied:
            continue
        if applied:
            backup_path = database_path.with_name(
                f"{database_path.stem}.pre-migration-v{version}.sqlite"
            )
            if not backup_path.exists():
                with sqlite3.connect(backup_path) as backup_connection:
                    connection.backup(backup_connection)
                os.chmod(backup_path, 0o600)
        migration_script = f"""
            BEGIN IMMEDIATE;
            {sql}
            INSERT INTO schema_migrations(version) VALUES ({version});
            COMMIT;
        """
        try:
            connection.executescript(migration_script)
        except sqlite3.Error:
            connection.rollback()
            raise


def initialize_registry_database(path: Path) -> None:
    with connect_database(path) as connection:
        _apply_migrations(connection, REGISTRY_MIGRATIONS, path)


def initialize_goal_database(path: Path, goal_id: str, created_at: str) -> None:
    with connect_database(path) as connection:
        _apply_migrations(connection, GOAL_MIGRATIONS, path)
        existing = connection.execute("SELECT id FROM goal_identity").fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO goal_identity(id, created_at) VALUES (?, ?)",
                (goal_id, created_at),
            )
            connection.execute(
                "INSERT INTO audit_log(event_type, payload_json, occurred_at) VALUES (?, ?, ?)",
                ("goal_database_created", f'{{"goal_id":"{goal_id}"}}', created_at),
            )
            connection.commit()
        elif existing["id"] != goal_id:
            raise RuntimeError("Goal database identity does not match its registry goal.")

-- SQLite schema of the snapshot store (architecture section 6.4).
-- Shipped as package data; spot_report.store.sqlite_store runs it on a new database.
-- Change it only together with SCHEMA_VERSION and a migration.

CREATE TABLE schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);

INSERT INTO schema_version (id, version) VALUES (1, 1);

CREATE TABLE school (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE wave (
    id                    INTEGER PRIMARY KEY,
    school_id             TEXT NOT NULL REFERENCES school(id),
    label                 TEXT NOT NULL,
    fieldwork_start       TEXT,
    fieldwork_end         TEXT NOT NULL,
    limesurvey_id         INTEGER,
    questionnaire_version TEXT NOT NULL,
    program_version       TEXT NOT NULL,
    metrics_version       INTEGER NOT NULL,
    quality_rules_version TEXT,
    archive_path          TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE (school_id, label)
);

CREATE TABLE metric (
    wave_id   INTEGER NOT NULL REFERENCES wave(id) ON DELETE CASCADE,
    metric_id TEXT NOT NULL,
    kind      TEXT NOT NULL,     -- proportion | summary | distribution | pattern_counts
    payload   TEXT NOT NULL,     -- JSON
    PRIMARY KEY (wave_id, metric_id)
);

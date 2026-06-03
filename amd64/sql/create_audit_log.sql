-- Schéma pipeline_audit_log
-- Base séparée de l'instance Odoo (conformité Ley 1581)
-- À exécuter UNE SEULE FOIS sur la base PostgreSQL dédiée

CREATE TABLE IF NOT EXISTS pipeline_audit_log (
    id                    BIGSERIAL PRIMARY KEY,
    doc_id                TEXT NOT NULL,
    source                TEXT,                    -- 'email' | 'upload' | 'whatsapp'
    raw_s3_path           TEXT,
    extraction_engine     TEXT,                    -- 'pdfplumber' | 'google_docai' | 'tesseract'
    extraction_confidence FLOAT,
    nit_extracted         TEXT,
    nit_valid             BOOLEAN,
    needs_hitl            BOOLEAN DEFAULT FALSE,
    hitl_operator         TEXT,
    odoo_partner_id       INTEGER,
    odoo_action           TEXT,                    -- 'created' | 'updated' | 'skipped' | 'failed'
    error_message         TEXT,
    duration_ms           INTEGER,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at   ON pipeline_audit_log (created_at);
CREATE INDEX IF NOT EXISTS idx_audit_odoo_action  ON pipeline_audit_log (odoo_action);
CREATE INDEX IF NOT EXISTS idx_audit_nit          ON pipeline_audit_log (nit_extracted);
CREATE INDEX IF NOT EXISTS idx_audit_doc_id       ON pipeline_audit_log (doc_id);
CREATE INDEX IF NOT EXISTS idx_audit_needs_hitl   ON pipeline_audit_log (needs_hitl) WHERE needs_hitl = TRUE;

-- Retries de pré-qualification différés (sources DIAN/RUES indisponibles)
CREATE TABLE IF NOT EXISTS prequal_retries (
    id               BIGSERIAL PRIMARY KEY,
    nit              TEXT NOT NULL,
    partner_id       INTEGER NOT NULL,
    lead_id          INTEGER,
    fuentes_fallidas TEXT[] NOT NULL,          -- sources à relancer
    score_partiel    INTEGER NOT NULL,         -- score sans les sources manquantes
    semaforo_prev    TEXT NOT NULL,            -- semáforo provisoire posté dans Odoo
    retry_after      TIMESTAMPTZ NOT NULL,     -- quand relancer (J+1 même heure)
    retried_at       TIMESTAMPTZ,             -- NULL = en attente
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_retries_pending
    ON prequal_retries (retry_after)
    WHERE retried_at IS NULL;

-- 004_product_catalog_v2_create.sql
-- ----------------------------------------------------------------------------
-- Blue-green Phase 1 of the product_catalog redesign (2026-05-04).
--
-- Goal
-- ----
-- The current product_catalog is xlsx-shaped (24 columns including
-- source_file_path / source_sheet / source_row_number / raw_row /
-- business_line_key / product_type / format) and treats antibody-specific
-- fields (host / isotype / clone / immunogen / formulation / storage /
-- dilutions / etc.) as opaque attributes JSONB keys. With antibody
-- switching to web (promab.com __NEXT_DATA__) as the source of truth,
-- those fields become first-class and the xlsx-provenance columns become
-- dead.
--
-- This phase creates an empty product_catalog_v2 with the redesigned
-- schema. No data motion yet — phases 2-4 happen in subsequent migrations
-- and out-of-band scripts:
--
--   004 (this file): CREATE TABLE product_catalog_v2 + indexes + trigger
--   005:             INSERT INTO v2 SELECT non-antibody rows from old
--                    product_catalog (CAR-T / mRNA / other business lines)
--   (out of band):   scripts/import_antibody_from_jsonl.py populates v2
--                    from the web JSONL (~4080 rows)
--   (code switch):   src/catalog/retrieval/* SQL switches to query v2
--   (verify):        webui smoke tests, both antibody + CAR-T flows
--   006:             DROP TABLE product_catalog;
--                    ALTER TABLE product_catalog_v2 RENAME TO product_catalog
--
-- Each phase is independently rollback-able until 006.
-- ----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;


-- ---------------------------------------------------------------------------
-- Helper: text normalisation for trigram search materialisation.
-- Idempotent CREATE OR REPLACE so this migration is safe to rerun.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION normalize_catalog_text(input_text TEXT)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT NULLIF(
        regexp_replace(
            lower(unaccent(coalesce(input_text, ''))),
            '\s+',
            ' ',
            'g'
        ),
        ''
    );
$$;


-- ---------------------------------------------------------------------------
-- Trigger function: keep search_text + updated_at fresh on INSERT/UPDATE.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION refresh_product_catalog_v2_search()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.search_text := normalize_catalog_text(
        concat_ws(
            ' ',
            NEW.catalog_no,
            NEW.business_line,
            NEW.record_type,
            NEW.name,
            NEW.target_antigen,
            NEW.host,
            NEW.isotype,
            NEW.clone,
            NEW.gene_id,
            NEW.molecular_weight,
            (
                SELECT string_agg(value, ' ')
                FROM jsonb_array_elements_text(NEW.aliases)
            ),
            (
                SELECT string_agg(value, ' ')
                FROM jsonb_array_elements_text(NEW.applications)
            ),
            (
                SELECT string_agg(value, ' ')
                FROM jsonb_array_elements_text(NEW.species_reactivity)
            )
        )
    );
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;


-- ---------------------------------------------------------------------------
-- product_catalog_v2 — redesigned unified product catalog.
--
-- Column groups
-- -------------
-- 1. Identity (id, catalog_no)
-- 2. Classification (business_line, record_type)
-- 3. Naming (name, web_handle, target_antigen)
-- 4. Antibody-specific first-class columns (host / isotype / clone /
--    molecular_weight / gene_id / sequence / dilutions / immunogen /
--    formulation / storage / shipping_information / description_html /
--    references_text). NULL for CAR-T / mRNA / other lines.
-- 5. Pricing (price, price_variants for multi-tier, currency, size, lead_time_text)
-- 6. Collections (aliases / aliases_normalized / applications /
--    species_reactivity / web_tags) — JSONB arrays.
-- 7. Free-form extension (attributes JSONB) — preserved from old schema.
--    CAR-T / mRNA still use this bag for fields not yet promoted to
--    dedicated columns (construct, group_*, marker, etc.). Future
--    business-line web migrations may promote these the same way
--    antibody promotes immunogen / formulation / etc.
-- 8. Source & audit (image_url, source_url, raw_metafields,
--    last_synced_at, is_active, created_at, updated_at).
-- 9. Search (search_text auto-built by trigger).
--
-- Compared to the previous product_catalog, this drops 7 columns:
--   source_file_path, source_sheet, source_row_number  -- xlsx provenance
--   raw_row                                              -- xlsx echo
--   business_line_key                                    -- redundant w/ business_line
--   product_type, format                                 -- xlsx-shaped, replaced
--                                                          by record_type + size
-- and adds 22 columns (the antibody-specific block + web/audit fields).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_catalog_v2 (
    -- Primary identity
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_no          TEXT            NOT NULL,

    -- Classification
    business_line       TEXT            NOT NULL,                       -- "Antibody" / "CAR-T/CAR-NK Development" / "mRNA-LNP" / etc.
    record_type         TEXT,                                           -- "Rabbit Polyclonal" / "Mouse Monoclonal" / "CAR-T Cells" / etc.

    -- Naming
    name                TEXT            NOT NULL,
    web_handle          TEXT,                                           -- URL slug part, e.g. "cebpb-primary-antibody-10005"
    target_antigen      TEXT,

    -- Antibody-specific first-class columns
    host                TEXT,                                           -- "Rabbit" / "Mouse" / "Rat"
    isotype             TEXT,                                           -- "IgG" / "IgG1" / "IgG2a"
    clone               TEXT,                                           -- monoclonal clone designation; NULL for poly
    molecular_weight    TEXT,                                           -- "36kDa" — opaque text (preserve unit)
    gene_id             TEXT,                                           -- Entrez Gene ID
    sequence            TEXT,
    elisa_dilution      TEXT,                                           -- "1/10000"
    wb_dilution         TEXT,                                           -- "1/500 - 1/2000"
    ihc_dilution        TEXT,
    immunogen           TEXT,
    formulation         TEXT,
    storage             TEXT,
    shipping_information TEXT,
    description_html    TEXT,                                           -- web bodyHtml verbatim
    references_text     TEXT,                                           -- metafields.references

    -- Pricing
    price               NUMERIC(14,2),
    price_variants      JSONB,                                          -- multi-tier pricing (CAR-T 1×10⁶ → $X / 1×10⁷ → $Y) — NULL for single-size
    currency            TEXT            NOT NULL DEFAULT 'USD',
    size                TEXT,                                           -- "100μl" / "1×10⁶ cells"
    lead_time_text      TEXT,

    -- Collections
    aliases             JSONB           NOT NULL DEFAULT '[]'::jsonb,
    aliases_normalized  JSONB           NOT NULL DEFAULT '[]'::jsonb,
    applications        JSONB           NOT NULL DEFAULT '[]'::jsonb,
    species_reactivity  JSONB           NOT NULL DEFAULT '[]'::jsonb,
    web_tags            JSONB           NOT NULL DEFAULT '[]'::jsonb,

    -- Free-form extension (CAR-T / mRNA continue to use this until they
    -- get their own web migration with promoted columns)
    attributes          JSONB           NOT NULL DEFAULT '{}'::jsonb,

    -- Source & audit
    image_url           TEXT,
    source_url          TEXT,                                           -- the page we scraped from (NULL for xlsx-sourced rows)
    raw_metafields      JSONB,                                          -- raw web metafields kept verbatim — future-proofing; NULL for xlsx-sourced
    last_synced_at      TIMESTAMPTZ,                                    -- when web data was scraped; NULL for xlsx-sourced
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Search materialisation (trigger-maintained)
    search_text         TEXT,

    -- ----------------------------------------------------------------------
    -- Constraints
    -- ----------------------------------------------------------------------
    -- catalog_no is the natural key for catalog lookups; uniqueness was
    -- enforced in the previous schema and remains.
    CONSTRAINT uq_pcv2_catalog_no UNIQUE (catalog_no),

    -- aliases and aliases_normalized must stay 1:1 in length so downstream
    -- index lookups can pivot between display and matching forms.
    -- (Mirrors the existing chk_aliases_normalized_length constraint.)
    CONSTRAINT chk_pcv2_aliases_normalized_length CHECK (
        jsonb_array_length(aliases) = jsonb_array_length(aliases_normalized)
    )
);


COMMENT ON TABLE product_catalog_v2 IS
    'Redesigned product catalog (blue-green migration target, 2026-05-04). Once 005-006 are applied this becomes the canonical product_catalog. Antibody fields are first-class columns sourced from web; CAR-T / mRNA continue to use the attributes JSONB bag pending their own web migrations.';

COMMENT ON COLUMN product_catalog_v2.business_line IS
    '业务线 ("Antibody" / "CAR-T/CAR-NK Development" / "mRNA-LNP" / "Custom Service" 等). 必填,因为很多检索路径按 business_line 过滤.';
COMMENT ON COLUMN product_catalog_v2.record_type IS
    '记录子类型 (e.g. "Rabbit Polyclonal" / "Mouse Monoclonal" / "CAR-T Cells").';
COMMENT ON COLUMN product_catalog_v2.host IS
    '抗体宿主物种. NULL 对非抗体 / 不适用.';
COMMENT ON COLUMN product_catalog_v2.isotype IS
    '免疫球蛋白型 ("IgG" / "IgG1" 等). NULL 对非抗体.';
COMMENT ON COLUMN product_catalog_v2.clone IS
    '克隆名 (monoclonal 才有). NULL 对 polyclonal / 非抗体.';
COMMENT ON COLUMN product_catalog_v2.elisa_dilution IS
    'ELISA 推荐稀释比例 (e.g. "1/10000"). 直接入 draft 给 CSR 看.';
COMMENT ON COLUMN product_catalog_v2.wb_dilution IS
    'Western Blot 推荐稀释比例 (e.g. "1/500 - 1/2000").';
COMMENT ON COLUMN product_catalog_v2.immunogen IS
    '免疫原描述 (peptide sequence / fusion protein / etc.).';
COMMENT ON COLUMN product_catalog_v2.formulation IS
    '配方/纯化描述 (purification + buffer + 防腐剂 etc.).';
COMMENT ON COLUMN product_catalog_v2.storage IS
    '存储条件 (e.g. "4°C; -20°C for long term storage").';
COMMENT ON COLUMN product_catalog_v2.description_html IS
    'Web bodyHtml verbatim (CSR 看 draft 时可见完整产品描述).';
COMMENT ON COLUMN product_catalog_v2.references_text IS
    'Metafields.references — 引用文献列表(HTML 拼接,保留原貌).';
COMMENT ON COLUMN product_catalog_v2.price_variants IS
    '多 size tier 定价 ([{"size":"1×10⁶","price":900},...]). 仅 CAR-T 等多档商品使用; 抗体单 size 用 price + size 即可.';
COMMENT ON COLUMN product_catalog_v2.attributes IS
    '通用 free-form bag. CAR-T / mRNA-LNP 暂时还用这里存 construct / group_* / marker / 等 (pending 各自 web migration).';
COMMENT ON COLUMN product_catalog_v2.raw_metafields IS
    '完整 web metafields 字典,留作未来字段扩展或 audit. NULL 对 xlsx-sourced rows.';
COMMENT ON COLUMN product_catalog_v2.source_url IS
    'Web 页面 URL,反查用. NULL 对 xlsx-sourced rows.';
COMMENT ON COLUMN product_catalog_v2.last_synced_at IS
    'Web 抓取时间. NULL 对 xlsx-sourced rows.';


-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
-- catalog_no UNIQUE index is auto-created by the constraint above.
-- id PK index is auto-created.

CREATE INDEX IF NOT EXISTS idx_pcv2_business_line
    ON product_catalog_v2 (business_line);

CREATE INDEX IF NOT EXISTS idx_pcv2_record_type
    ON product_catalog_v2 (record_type) WHERE record_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pcv2_host
    ON product_catalog_v2 (host) WHERE host IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pcv2_target_antigen
    ON product_catalog_v2 (target_antigen) WHERE target_antigen IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_pcv2_aliases_normalized_gin
    ON product_catalog_v2 USING gin (aliases_normalized);

CREATE INDEX IF NOT EXISTS idx_pcv2_applications_gin
    ON product_catalog_v2 USING gin (applications);

CREATE INDEX IF NOT EXISTS idx_pcv2_species_reactivity_gin
    ON product_catalog_v2 USING gin (species_reactivity);

CREATE INDEX IF NOT EXISTS idx_pcv2_search_trgm
    ON product_catalog_v2 USING gin (search_text gin_trgm_ops);


-- ---------------------------------------------------------------------------
-- Trigger
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_refresh_pcv2_search ON product_catalog_v2;
CREATE TRIGGER trg_refresh_pcv2_search
    BEFORE INSERT OR UPDATE ON product_catalog_v2
    FOR EACH ROW EXECUTE FUNCTION refresh_product_catalog_v2_search();

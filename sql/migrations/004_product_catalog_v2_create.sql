-- 004_product_catalog_v2_create.sql
-- ----------------------------------------------------------------------------
-- Blue-green Phase 1 of the product_catalog redesign (2026-05-04, CTI revision).
--
-- Architecture: Class Table Inheritance (CTI)
-- -------------------------------------------
-- product_catalog_v2          -- parent: shared columns for every business line
-- antibody_product_catalog_v2 -- child: antibody-only first-class columns
--                                (host / isotype / dilutions / immunogen / etc.),
--                                1:1 with parent via product_id PK + FK.
--
-- CAR-T / mRNA-LNP do NOT get a child table in this migration. Their
-- per-line fields (construct / group_* / costimulatory_domain / cell_number /
-- etc.) continue living in the parent table's attributes JSONB bag, since
-- (a) data volume is small (138 + 112 = 250 rows on 2026-05-04),
-- (b) the field set is not yet stable enough to promote, and
-- (c) those lines have no web migration scheduled yet — when they do, each
--     gets its own child table cloned from this antibody pattern.
--
-- Why CTI instead of one wide table:
--   * The current product_catalog is a single 24-column table where 17
--     antibody-only fields would sit NULL on every CAR-T / mRNA row, and
--     the parent table would keep accreting columns as more business lines
--     promote out of attributes.
--   * CTI lets each child table model its own domain precisely — antibody
--     can add fields without touching CAR-T / mRNA, and vice versa.
--
-- Trade-off accepted: detail lookups by catalog_no become a LEFT JOIN
-- between parent and child. Cross-line searches (alias / full-text /
-- catalog_no resolution) still hit the parent only, no JOIN.
--
-- Phase plan
-- ----------
--   004 (this file): CREATE parent + antibody child + indexes + trigger
--   005:             INSERT non-antibody rows from old product_catalog
--                    into the parent only (no antibody child rows)
--   (out of band):   scripts/import_antibody_from_jsonl.py populates BOTH
--                    parent + antibody child from the web JSONL (~4080 rows)
--   (code switch):   src/catalog/retrieval/* SQL switches to query v2
--                    (with LEFT JOIN antibody child where antibody detail
--                    is needed)
--   (verify):        webui smoke tests, both antibody + CAR-T flows
--   006:             DROP old product_catalog;
--                    RENAME product_catalog_v2 → product_catalog;
--                    RENAME antibody_product_catalog_v2 → antibody_product_catalog
--
-- Each phase is independently rollback-able until 006.
-- ----------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;


-- ---------------------------------------------------------------------------
-- Helper: text normalisation for trigram search materialisation.
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
-- Trigger function: keep parent.search_text + parent.updated_at fresh.
-- Only references parent columns — child antibody fields are NOT included
-- in search_text. Rationale: the parent's name + record_type already carry
-- "Rabbit Polyclonal antibody to <antigen>" style strings (which subsume
-- host / isotype / antigen at the lexical level), and forcing the trigger
-- to reach into a child table would couple parent maintenance to child
-- presence and break the layering.
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


-- ===========================================================================
-- Parent table: product_catalog_v2
-- ---------------------------------------------------------------------------
-- Holds columns common to every business line. CAR-T / mRNA / Custom Service
-- live entirely in this table (their line-specific fields go into
-- attributes JSONB until a future migration promotes them into their own
-- child table). Antibody rows have their line-specific fields in the
-- antibody_product_catalog_v2 child table.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS product_catalog_v2 (
    -- Primary identity
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    catalog_no          TEXT            NOT NULL,

    -- Classification
    business_line       TEXT            NOT NULL,                       -- "Antibody" / "CAR-T/CAR-NK Development" / "mRNA-LNP" / "Custom Service" 等
    record_type         TEXT,                                           -- "Rabbit Polyclonal" / "Mouse Monoclonal" / "cell_product" / "Protein" 等

    -- Naming
    name                TEXT            NOT NULL,
    target_antigen      TEXT,                                           -- antibody 行可后续从 name 抽取

    -- Pricing
    price               NUMERIC(14,2),
    price_variants      JSONB,                                          -- 多 size tier 定价 ([{"size":"1×10⁶","price":900},...]); NULL 表示单 size
    currency            TEXT            NOT NULL DEFAULT 'USD',
    size                TEXT,                                           -- "100μl" / "1×10⁶ cells" / "10ug in 200ul"
    lead_time_text      TEXT,

    -- Collections
    aliases             JSONB           NOT NULL DEFAULT '[]'::jsonb,
    aliases_normalized  JSONB           NOT NULL DEFAULT '[]'::jsonb,
    applications        JSONB           NOT NULL DEFAULT '[]'::jsonb,   -- antibody: ["WB","ELISA","IHC"]; CAR-T: 空
    species_reactivity  JSONB           NOT NULL DEFAULT '[]'::jsonb,   -- antibody: ["Human","Mouse"]; CAR-T: 空
    web_tags            JSONB           NOT NULL DEFAULT '[]'::jsonb,

    -- Free-form bag for line-specific fields not yet promoted to child tables.
    -- CAR-T:  construct / group_name / group_type / costimulatory_domain /
    --         marker / cell_number / unit / group_summary / group_subtype
    -- mRNA-LNP: (currently empty post-promotion of product_type / format)
    -- Future business-line web migrations may promote these into their own
    -- child tables (e.g. cart_product_catalog) the way antibody does here.
    attributes          JSONB           NOT NULL DEFAULT '{}'::jsonb,

    -- Source & audit
    image_url           TEXT,
    source_url          TEXT,                                           -- web URL,xlsx-sourced 行为 NULL
    web_handle          TEXT,                                           -- URL slug,如 "cebpb-primary-antibody-10005"
    is_active           BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_synced_at      TIMESTAMPTZ,                                    -- web 抓取时间; xlsx-sourced 行为 NULL

    -- Search materialisation (trigger-maintained,parent-only fields)
    search_text         TEXT,

    -- ----------------------------------------------------------------------
    -- Constraints
    -- ----------------------------------------------------------------------
    CONSTRAINT uq_pcv2_catalog_no UNIQUE (catalog_no),
    CONSTRAINT chk_pcv2_aliases_normalized_length CHECK (
        jsonb_array_length(aliases) = jsonb_array_length(aliases_normalized)
    )
);


COMMENT ON TABLE product_catalog_v2 IS
    'CTI parent table: shared columns for every business line. Antibody-only fields live in antibody_product_catalog_v2 (1:1 child). CAR-T / mRNA-LNP currently use the attributes JSONB bag pending their own future child tables.';

COMMENT ON COLUMN product_catalog_v2.business_line IS
    '业务线 ("Antibody" / "CAR-T/CAR-NK Development" / "mRNA-LNP" / "Custom Service" 等).';
COMMENT ON COLUMN product_catalog_v2.record_type IS
    '记录子类型 (e.g. "Rabbit Polyclonal" / "Mouse Monoclonal" / "cell_product" / "Protein").';
COMMENT ON COLUMN product_catalog_v2.attributes IS
    '通用 free-form bag. CAR-T 暂时存 construct / group_* / marker / cell_number 等 (pending CAR-T web migration).';
COMMENT ON COLUMN product_catalog_v2.price_variants IS
    '多 size tier 定价 ([{"size":"1×10⁶","price":900},...]). 仅 CAR-T 等多档商品使用;antibody 单 size 用 price + size 即可.';


-- ---------------------------------------------------------------------------
-- Indexes (parent)
-- ---------------------------------------------------------------------------
-- catalog_no UNIQUE index is auto-created by the constraint above.
-- id PK index is auto-created.

CREATE INDEX IF NOT EXISTS idx_pcv2_business_line
    ON product_catalog_v2 (business_line);

CREATE INDEX IF NOT EXISTS idx_pcv2_record_type
    ON product_catalog_v2 (record_type) WHERE record_type IS NOT NULL;

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
-- Trigger (parent)
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_refresh_pcv2_search ON product_catalog_v2;
CREATE TRIGGER trg_refresh_pcv2_search
    BEFORE INSERT OR UPDATE ON product_catalog_v2
    FOR EACH ROW EXECUTE FUNCTION refresh_product_catalog_v2_search();


-- ===========================================================================
-- Child table: antibody_product_catalog_v2
-- ---------------------------------------------------------------------------
-- 1:1 with product_catalog_v2 (one row per antibody product). Holds the
-- antibody-only first-class columns sourced from the web (promab.com
-- __NEXT_DATA__ metafields). FK ON DELETE CASCADE so removing a parent
-- product also removes its antibody facet automatically.
--
-- Column groups
--   * Identity & physical: host / isotype / clone / molecular_weight / gene_id / sequence
--   * Recommended dilutions: elisa / wb / ihc / icc / fcm
--   * Provenance & narrative: immunogen / formulation / storage /
--     shipping_information / description_html / references_text
--   * Raw extension: raw_metafields JSONB — verbatim web metafields dict
--     for future-proofing when new fields appear on the storefront.
-- ===========================================================================
CREATE TABLE IF NOT EXISTS antibody_product_catalog_v2 (
    product_id          UUID            PRIMARY KEY
        REFERENCES product_catalog_v2(id) ON DELETE CASCADE,

    -- Identity & physical
    host                TEXT,                                           -- "Rabbit" / "Mouse" / "Rat"
    isotype             TEXT,                                           -- "IgG" / "IgG1" / "IgG, Kappa" / "Mouse IgG2a"
    clone               TEXT,                                           -- monoclonal clone designation; NULL for poly
    molecular_weight    TEXT,                                           -- "36kDa" — opaque text (preserve unit)
    gene_id             TEXT,                                           -- Entrez Gene ID (~99% antibody fill)
    sequence            TEXT,                                           -- amino-acid sequence; web sentinel "N" maps to NULL on import

    -- Recommended dilutions (5 applications)
    elisa_dilution      TEXT,                                           -- "1/10000"           ~99% antibody fill
    wb_dilution         TEXT,                                           -- "1/500 - 1/2000"   ~97% antibody fill
    fcm_dilution        TEXT,                                           -- FACS / flow cytometry  ~61% antibody fill
    ihc_dilution        TEXT,                                           --                     ~51% antibody fill
    icc_dilution        TEXT,                                           --                     ~27% antibody fill

    -- Provenance & narrative
    immunogen           TEXT,                                           -- "Synthetic peptide of human HSF2..."
    formulation         TEXT,                                           -- 配方/纯化/buffer/防腐剂
    storage             TEXT,                                           -- "4&deg;C; -20&deg;C for long term storage" (HTML entities preserved)
    shipping_information TEXT,
    description_html    TEXT,                                           -- web bodyHtml verbatim
    references_text     TEXT,                                           -- metafields.references — HTML <br /> 拼接的引用列表

    -- Raw extension
    raw_metafields      JSONB                                           -- 完整 web metafields 字典留底,future-proofing
);


COMMENT ON TABLE antibody_product_catalog_v2 IS
    'CTI child of product_catalog_v2: antibody-only first-class fields sourced from promab.com web. 1:1 with parent via product_id PK + FK CASCADE.';

COMMENT ON COLUMN antibody_product_catalog_v2.host IS
    '抗体宿主物种 ("Rabbit" / "Mouse" / "Rat"). Web __NEXT_DATA__ metafields.host.';
COMMENT ON COLUMN antibody_product_catalog_v2.isotype IS
    '免疫球蛋白型. Web 数据偶含 "Mouse IgG1" 这种 host+isotype 复合形式,保留原貌.';
COMMENT ON COLUMN antibody_product_catalog_v2.clone IS
    '克隆名. Polyclonal 也常有(web 数据如此),保留原貌.';
COMMENT ON COLUMN antibody_product_catalog_v2.elisa_dilution IS
    'ELISA 推荐稀释比例 (e.g. "1/10000"). Draft 给 CSR 看时直接 surface.';
COMMENT ON COLUMN antibody_product_catalog_v2.wb_dilution IS
    'Western Blot 推荐稀释比例 (e.g. "1/500 - 1/2000").';
COMMENT ON COLUMN antibody_product_catalog_v2.fcm_dilution IS
    'Flow cytometry / FACS 推荐稀释 (web key: metafields.fcm).';
COMMENT ON COLUMN antibody_product_catalog_v2.ihc_dilution IS
    'IHC 推荐稀释 (web key: metafields.ihc).';
COMMENT ON COLUMN antibody_product_catalog_v2.icc_dilution IS
    'ICC 推荐稀释 (web key: metafields.icc).';
COMMENT ON COLUMN antibody_product_catalog_v2.immunogen IS
    '免疫原描述 (peptide sequence / fusion protein / etc.).';
COMMENT ON COLUMN antibody_product_catalog_v2.formulation IS
    '配方/纯化/buffer/防腐剂 描述.';
COMMENT ON COLUMN antibody_product_catalog_v2.storage IS
    '存储条件. HTML entity 原貌保留 (e.g. "4&deg;C"); 显示层负责 unescape.';
COMMENT ON COLUMN antibody_product_catalog_v2.description_html IS
    'Web bodyHtml verbatim. CSR 看 draft 时可见完整产品描述.';
COMMENT ON COLUMN antibody_product_catalog_v2.references_text IS
    'Metafields.references — HTML <br /> 拼接的引用文献列表,保留原貌.';
COMMENT ON COLUMN antibody_product_catalog_v2.raw_metafields IS
    '完整 web metafields 字典,留作未来字段扩展或 audit 反查.';


-- ---------------------------------------------------------------------------
-- Indexes (child)
-- ---------------------------------------------------------------------------
-- product_id PK index is auto-created.
-- Filter indexes for common antibody-shaped queries:

CREATE INDEX IF NOT EXISTS idx_apcv2_host
    ON antibody_product_catalog_v2 (host) WHERE host IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_apcv2_isotype
    ON antibody_product_catalog_v2 (isotype) WHERE isotype IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_apcv2_gene_id
    ON antibody_product_catalog_v2 (gene_id) WHERE gene_id IS NOT NULL;

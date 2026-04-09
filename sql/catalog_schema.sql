CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Enable pgvector only when semantic search is needed.
-- CREATE EXTENSION IF NOT EXISTS vector;

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

CREATE OR REPLACE FUNCTION refresh_catalog_search_fields()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.display_name := coalesce(
        NEW.display_name,
        NEW.name,
        NEW.catalog_no
    );

    NEW.search_text := normalize_catalog_text(
        concat_ws(
            ' ',
            NEW.catalog_no,
            NEW.business_line,
            NEW.record_type,
            NEW.display_name,
            NEW.name,
            NEW.description,
            NEW.clone_name,
            NEW.isotype,
            NEW.ig_class,
            NEW.gene_id,
            NEW.gene_accession,
            NEW.swissprot,
            NEW.also_known_as,
            NEW.application_text,
            NEW.species_reactivity_text,
            NEW.target_antigen,
            NEW.costimulatory_domain,
            NEW.construct,
            NEW.group_name,
            NEW.group_type,
            NEW.group_subtype,
            NEW.group_summary,
            NEW.product_type,
            NEW.format,
            NEW.marker,
            NEW.price_text,
            NEW.lead_time_text
        )
    );

    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS catalog_source (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),                    -- 来源记录主键
    source_name TEXT NOT NULL,                                       -- 来源名称，例如文件名
    source_type TEXT NOT NULL DEFAULT 'excel',                       -- 来源类型，例如 excel / manual
    file_path TEXT,                                                  -- 来源文件路径
    source_version TEXT,                                             -- 来源版本号或批次号
    note TEXT,                                                       -- 来源备注
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP        -- 来源记录创建时间
);

COMMENT ON TABLE catalog_source IS 'Tracks imported catalog files, sheets, and versions.';

CREATE TABLE IF NOT EXISTS product_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),                    -- 商品记录主键

    -- Import lineage
    source_id UUID REFERENCES catalog_source(id) ON DELETE SET NULL, -- 对应 catalog_source.id
    source_type TEXT NOT NULL DEFAULT 'excel',                       -- 数据来源类型，例如 excel / manual
    source_name TEXT,                                                -- 来源名称，通常是文件名
    source_file_path TEXT,                                           -- 来源文件完整路径
    source_sheet TEXT,                                               -- Excel 的 sheet 名
    source_row_number INTEGER,                                       -- Excel 中的行号

    -- High-level classification
    business_line TEXT NOT NULL,                                     -- 业务线，例如 Antibody / CAR-T / mRNA-LNP
    record_type TEXT,                                                -- 记录类型，例如 Monoclonal Antibody / custom_service

    -- Common identifiers / names
    catalog_no TEXT,                                                 -- 产品目录编号 / catalog no
    name TEXT,                                                       -- 统一主名称
    display_name TEXT,                                               -- 前端展示或对外查询使用的名称
    description TEXT,                                                -- 补充说明或描述信息

    -- Antibody-related columns
    antibody_type TEXT,                                              -- 抗体类型，例如 monoclonal / polyclonal
    clone_name TEXT,                                                 -- clone 名称
    isotype TEXT,                                                    -- 单抗对应的 isotype
    ig_class TEXT,                                                   -- 多抗对应的 Ig class
    gene_id TEXT,                                                    -- Gene ID
    gene_accession TEXT,                                             -- Gene Accession
    swissprot TEXT,                                                  -- SwissProt 编号
    also_known_as TEXT,                                              -- 别名 / 同义词
    application_text TEXT,                                           -- 应用场景，例如 ELISA、WB、IHC
    species_reactivity_text TEXT,                                    -- 物种反应性，例如 Human / Mouse / Rat

    -- CAR-T / cell-product columns
    target_antigen TEXT,                                             -- CAR-T 目标抗原
    costimulatory_domain TEXT,                                       -- 共刺激结构域
    construct TEXT,                                                  -- construct 描述
    unit TEXT,                                                       -- 单位
    cell_number TEXT,                                                -- 细胞数量
    marker TEXT,                                                     -- marker 信息
    group_name TEXT,                                                 -- 分组名称
    group_type TEXT,                                                 -- 分组类型
    group_subtype TEXT,                                              -- 分组子类型
    group_summary TEXT,                                              -- 分组摘要说明

    -- mRNA-LNP / service columns
    product_type TEXT,                                               -- 产品类型，例如 Protein
    format TEXT,                                                     -- 规格/包装格式，例如 10ug in 200ul

    -- Pricing / delivery
    currency TEXT NOT NULL DEFAULT 'USD',                            -- 币种
    price NUMERIC(14, 2),                                            -- 标准数值价格
    price_text TEXT,                                                 -- 原始价格文本，适合非标准价格
    lead_time_text TEXT,                                             -- 原始交期文本

    -- Search-friendly multi-value fields
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,                      -- 结构化别名列表
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,                     -- 结构化关键词列表
    applications JSONB NOT NULL DEFAULT '[]'::jsonb,                 -- 结构化应用场景列表
    species_reactivity JSONB NOT NULL DEFAULT '[]'::jsonb,           -- 结构化物种反应性列表

    -- Raw ingestion preservation
    raw_row JSONB NOT NULL DEFAULT '{}'::jsonb,                      -- Excel 原始行数据
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,                 -- 额外原始元数据

    -- Search materialization
    search_text TEXT,                                                -- 用于 trigram 模糊搜索的聚合文本
    -- embedding VECTOR(1536),

    is_active BOOLEAN NOT NULL DEFAULT TRUE,                         -- 是否启用，便于软删除
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,       -- 记录创建时间
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,       -- 记录更新时间

    CONSTRAINT uq_product_catalog_source_row
        UNIQUE (source_file_path, source_sheet, source_row_number)   -- 同一来源文件同一 sheet 同一行只允许导入一次
);

COMMENT ON TABLE product_catalog IS 'Wide denormalized catalog table covering antibody, CAR-T, mRNA-LNP, and custom service pricing data.';
COMMENT ON COLUMN product_catalog.id IS '商品记录主键。';
COMMENT ON COLUMN product_catalog.source_id IS '关联的来源表主键。';
COMMENT ON COLUMN product_catalog.source_type IS '数据来源类型，例如 excel 或 manual。';
COMMENT ON COLUMN product_catalog.source_name IS '来源名称，通常为文件名。';
COMMENT ON COLUMN product_catalog.source_file_path IS '来源文件完整路径。';
COMMENT ON COLUMN product_catalog.source_sheet IS '来源 Excel 的 sheet 名称。';
COMMENT ON COLUMN product_catalog.source_row_number IS '来源 Excel 的原始行号。';
COMMENT ON COLUMN product_catalog.business_line IS '业务线。';
COMMENT ON COLUMN product_catalog.record_type IS '记录类型或子类。';
COMMENT ON COLUMN product_catalog.catalog_no IS '产品目录编号。';
COMMENT ON COLUMN product_catalog.name IS '统一主名称。';
COMMENT ON COLUMN product_catalog.display_name IS '展示和检索优先使用的名称。';
COMMENT ON COLUMN product_catalog.description IS '补充描述信息。';
COMMENT ON COLUMN product_catalog.antibody_type IS '抗体类型。';
COMMENT ON COLUMN product_catalog.clone_name IS 'clone 名称。';
COMMENT ON COLUMN product_catalog.isotype IS 'isotype。';
COMMENT ON COLUMN product_catalog.ig_class IS 'Ig class。';
COMMENT ON COLUMN product_catalog.gene_id IS 'Gene ID。';
COMMENT ON COLUMN product_catalog.gene_accession IS 'Gene Accession。';
COMMENT ON COLUMN product_catalog.swissprot IS 'SwissProt 编号。';
COMMENT ON COLUMN product_catalog.also_known_as IS '别名或同义词。';
COMMENT ON COLUMN product_catalog.application_text IS '应用场景原始文本。';
COMMENT ON COLUMN product_catalog.species_reactivity_text IS '物种反应性原始文本。';
COMMENT ON COLUMN product_catalog.target_antigen IS '目标抗原。';
COMMENT ON COLUMN product_catalog.costimulatory_domain IS '共刺激结构域。';
COMMENT ON COLUMN product_catalog.construct IS 'construct 描述。';
COMMENT ON COLUMN product_catalog.unit IS '单位。';
COMMENT ON COLUMN product_catalog.cell_number IS '细胞数量。';
COMMENT ON COLUMN product_catalog.marker IS 'marker 信息。';
COMMENT ON COLUMN product_catalog.group_name IS '分组名称。';
COMMENT ON COLUMN product_catalog.group_type IS '分组类型。';
COMMENT ON COLUMN product_catalog.group_subtype IS '分组子类型。';
COMMENT ON COLUMN product_catalog.group_summary IS '分组摘要。';
COMMENT ON COLUMN product_catalog.product_type IS '产品类型。';
COMMENT ON COLUMN product_catalog.format IS '规格或包装格式。';
COMMENT ON COLUMN product_catalog.currency IS '币种。';
COMMENT ON COLUMN product_catalog.price IS '标准数值价格。';
COMMENT ON COLUMN product_catalog.raw_row IS 'Original row payload from Excel after column-name normalization.';
COMMENT ON COLUMN product_catalog.price_text IS 'Stores non-standard price strings such as 0.5/base or 800/0.5mg.';
COMMENT ON COLUMN product_catalog.lead_time_text IS '原始交期文本。';
COMMENT ON COLUMN product_catalog.aliases IS '结构化别名列表。';
COMMENT ON COLUMN product_catalog.keywords IS '结构化关键词列表。';
COMMENT ON COLUMN product_catalog.applications IS '结构化应用场景列表。';
COMMENT ON COLUMN product_catalog.species_reactivity IS '结构化物种反应性列表。';
COMMENT ON COLUMN product_catalog.raw_metadata IS '原始扩展元数据。';
COMMENT ON COLUMN product_catalog.search_text IS 'Normalized plain-text field used for trigram fuzzy matching.';
COMMENT ON COLUMN product_catalog.is_active IS '是否启用。';
COMMENT ON COLUMN product_catalog.created_at IS '记录创建时间。';
COMMENT ON COLUMN product_catalog.updated_at IS '记录更新时间。';

DROP TRIGGER IF EXISTS trg_refresh_catalog_search_fields ON product_catalog;

CREATE TRIGGER trg_refresh_catalog_search_fields
BEFORE INSERT OR UPDATE ON product_catalog
FOR EACH ROW
EXECUTE FUNCTION refresh_catalog_search_fields();

CREATE INDEX IF NOT EXISTS idx_catalog_source_source_name
    ON catalog_source (source_name);

CREATE INDEX IF NOT EXISTS idx_product_catalog_source_id
    ON product_catalog (source_id);

CREATE INDEX IF NOT EXISTS idx_product_catalog_business_line
    ON product_catalog (business_line);

CREATE INDEX IF NOT EXISTS idx_product_catalog_record_type
    ON product_catalog (record_type);

CREATE INDEX IF NOT EXISTS idx_product_catalog_catalog_no
    ON product_catalog (catalog_no);

CREATE INDEX IF NOT EXISTS idx_product_catalog_price
    ON product_catalog (price);

CREATE INDEX IF NOT EXISTS idx_product_catalog_is_active
    ON product_catalog (is_active);

CREATE INDEX IF NOT EXISTS idx_product_catalog_updated_at
    ON product_catalog (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_product_catalog_catalog_no_trgm
    ON product_catalog
    USING GIN (catalog_no gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_product_catalog_display_name_trgm
    ON product_catalog
    USING GIN (display_name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_product_catalog_search_text_trgm
    ON product_catalog
    USING GIN (search_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_product_catalog_aliases_gin
    ON product_catalog
    USING GIN (aliases);

CREATE INDEX IF NOT EXISTS idx_product_catalog_keywords_gin
    ON product_catalog
    USING GIN (keywords);

CREATE INDEX IF NOT EXISTS idx_product_catalog_raw_row_gin
    ON product_catalog
    USING GIN (raw_row);

-- Optional vector index if embeddings are enabled later:
-- CREATE INDEX IF NOT EXISTS idx_product_catalog_embedding
--     ON product_catalog
--     USING ivfflat (embedding vector_cosine_ops)
--     WITH (lists = 100);

-- Example fuzzy search:
-- SELECT id, catalog_no, display_name, price, price_text
-- FROM product_catalog
-- WHERE search_text % normalize_catalog_text('cd19 car-t')
-- ORDER BY similarity(search_text, normalize_catalog_text('cd19 car-t')) DESC
-- LIMIT 20;

-- Example combined full-text + exact filtering:
-- SELECT id, catalog_no, display_name, business_line, price, price_text
-- FROM product_catalog
-- WHERE business_line = 'CAR-T/CAR-NK'
--   AND search_text % normalize_catalog_text('mock cd28')
-- ORDER BY similarity(search_text, normalize_catalog_text('mock cd28')) DESC;

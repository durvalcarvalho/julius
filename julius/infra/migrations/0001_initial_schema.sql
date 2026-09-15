CREATE TABLE stores (
    cnpj       TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    nickname   TEXT NOT NULL
);

CREATE TABLE products (
    id               INTEGER PRIMARY KEY,
    canonical_name   TEXT NOT NULL,
    content_quantity REAL,
    content_unit     TEXT CHECK (content_unit IN ('L', 'KG', 'UN'))
);

CREATE TABLE product_skus (
    store_cnpj   TEXT NOT NULL REFERENCES stores(cnpj),
    product_code TEXT NOT NULL,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    PRIMARY KEY (store_cnpj, product_code)
);

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE product_tags (
    product_id INTEGER NOT NULL REFERENCES products(id),
    tag_id     INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (product_id, tag_id)
);

CREATE TABLE prices (
    access_key   TEXT NOT NULL,
    item_index   INTEGER NOT NULL,
    purchased_at TEXT NOT NULL,          -- ISO 8601, from the receipt's "Emissão"
    store_cnpj   TEXT NOT NULL REFERENCES stores(cnpj),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    product_code TEXT NOT NULL,          -- raw value from that receipt; joins go through product_id
    description  TEXT NOT NULL,          -- raw value from that receipt
    quantity     REAL NOT NULL,
    unit         TEXT NOT NULL CHECK (unit IN ('UN', 'KG')),
    unit_price   REAL NOT NULL,
    total_price  REAL NOT NULL,
    PRIMARY KEY (access_key, item_index)
);

CREATE TABLE ai_usage (
    month     TEXT PRIMARY KEY,          -- 'YYYY-MM'
    spent_usd REAL NOT NULL DEFAULT 0
);

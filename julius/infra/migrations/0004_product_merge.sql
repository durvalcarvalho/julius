-- Merging becomes a reversible state instead of a destructive transformation: the absorbed
-- product keeps existing, with its own name, kind, content and tags. Stores the DIRECT target
-- (not the root): that is what makes unmerging restore the exactly previous state when a chain
-- has more than one level.
ALTER TABLE products ADD COLUMN merged_into INTEGER REFERENCES products(id);

-- One row per product, always, pointing at the root of its group. A product that was never
-- merged is its own root, so every read can join this view without a special case.
-- A cycle (A -> B and B -> A) makes this recursion never return, so the guard lives in the
-- write path (services/catalog.py), not in a column CHECK that cannot see two steps.
CREATE VIEW product_group AS
WITH RECURSIVE walk(product_id, current_id) AS (
    SELECT id, id FROM products
    UNION ALL
    SELECT w.product_id, p.merged_into FROM walk w JOIN products p ON p.id = w.current_id
     WHERE p.merged_into IS NOT NULL
)
SELECT w.product_id, w.current_id AS root_id
  FROM walk w JOIN products p ON p.id = w.current_id
 WHERE p.merged_into IS NULL;

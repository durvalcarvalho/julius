-- The name a group shows, as one definition. `repositories/products.py` composes the effective
-- product and `repositories/prices.py` names the rows of a group, and the DAG forbids one
-- repository importing the other — so duplicating the rule in SQL was the alternative, and this
-- view is what avoids the two screens drifting apart (measured: `produtos listar` said
-- "Tomate italiano União" while `consultar` said "TOMATE ITALIANO kg").
--
-- Orders by `merged_into IS NOT NULL` rather than by the root id because SQLite rejects an outer
-- alias inside the ORDER BY of a correlated subquery — and the root is the only member of a group
-- whose merged_into is NULL, so it means the same thing.
CREATE VIEW product_group_name AS
SELECT g.root_id,
       COALESCE((
           SELECT m.canonical_name FROM products m JOIN product_group gg ON gg.product_id = m.id
            WHERE gg.root_id = g.root_id
              AND NOT EXISTS (SELECT 1 FROM prices px
                               WHERE px.product_id = m.id AND px.description = m.canonical_name)
            ORDER BY (m.merged_into IS NOT NULL), m.id LIMIT 1
       ), root.canonical_name) AS canonical_name
  FROM product_group g JOIN products root ON root.id = g.root_id
 WHERE g.product_id = g.root_id;

-- Comparison group: "what kind of thing is this", so prices of the same kind can be compared
-- across stores. One column, not a table: a product belongs to at most one group, and a single
-- column makes that the database's rule instead of the application's.
ALTER TABLE products ADD COLUMN kind TEXT;

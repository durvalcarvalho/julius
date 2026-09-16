-- Address as printed on the receipt header; NULL until a receipt of that store is (re)imported.
ALTER TABLE stores ADD COLUMN address TEXT;

-- Aisle categories the AI is asked to prefer. Users add more with `julius produtos tag`.
INSERT OR IGNORE INTO tags (name) VALUES
    ('hortifruti'), ('carnes'), ('frios'), ('laticinios'), ('padaria'), ('mercearia'),
    ('bebidas'), ('limpeza'), ('higiene'), ('congelados'), ('temperos'), ('doces'), ('utilidades');

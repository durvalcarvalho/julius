-- Budget ledger for structured-decision providers (Choice/Score/Noul, e.g. TypeSafe/Jev) --
-- generic by `provider` from the start, so a second provider never asks for a migration of its
-- own. Separate from `ai_usage`, which is the free-text generation ledger (DeepSeek today).
-- See docs/design/structured-ai-decisions.md.
CREATE TABLE decision_usage (
    provider  TEXT NOT NULL,
    month     TEXT NOT NULL,   -- 'YYYY-MM'
    spent_usd REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, month)
);

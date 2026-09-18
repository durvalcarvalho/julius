# 170: `domain/formatting.py::weekday_phrase` — o dia da semana em vez de data + "há X dias"

> Uma função nova, mesma disciplina de `relative_age`: dado uma data ISO e um "hoje" injetável, devolve "hoje"/"ontem"/dia da semana/dia da semana passado — nunca a data numérica, que a rodada de humanização (v2.7.1) considerou redundante com a idade relativa.

## Contexto

Segue o design "humanização da voz do Julius (persona v3)" combinado em brainstorm/design na sessão de 2026-09-18 (screenshot real do bot mostrando texto em bloco único, `16/09/2026` ao lado de `há 2 dias`). Independente de qualquer outro ticket desta trilha — é só uma função pura nova.

## Escopo

### Dentro
- `weekday_phrase(purchased_at: str, *, today: date | None = None) -> str` em `julius/domain/formatting.py`.
- Faixas, pelos dias corridos entre `purchased_at` e `today` (ou `date.today()`):

| Dias atrás | Resultado |
|---|---|
| 0 | `"hoje"` |
| 1 | `"ontem"` |
| 2–7 | nome do dia da semana (`"quarta-feira"`) |
| 8–15 | nome do dia da semana + `" passada"` (`"quinta-feira passada"`) |
| 16+ | delega para `relative_age(purchased_at, today=today)` — mesmo texto que já existe ("há N semanas/meses/anos") |
| entrada inválida | `""`, mesmo comportamento de `br_date`/`relative_age` hoje |

- Nomes dos dias em português, minúsculos, com hífen: `segunda-feira`, `terça-feira`, `quarta-feira`, `quinta-feira`, `sexta-feira`, `sábado`, `domingo` (`date.weekday()`: 0 = segunda).

### Fora
- Qualquer uso da função (→ ticket 171). Este ticket só cria e testa `weekday_phrase` isoladamente.
- Mudar `relative_age`/`br_date` — continuam exatamente como estão; `weekday_phrase` só delega pra `relative_age` na faixa de 16+ dias, sem alterá-la.

## Requisitos

### Funcionais
- Assinatura idêntica em espírito a `relative_age`: `purchased_at: str`, `today: date | None = None` (mesmo motivo — teste de faixa não pode depender do dia em que roda).
- O corte de 15 dias é o mesmo que `relative_age` já usa pra trocar de "há N dias" pra "há N semanas" — não é coincidência, é reaproveitar a fronteira já medida na v2.5.1, não inventar uma nova.

### Validação e erros
- `purchased_at` com menos de 10 caracteres, ou não parseável como `date.fromisoformat`, devolve `""` (mesmo padrão de `relative_age`/`br_date`).
- Data no futuro (dias negativos) cai no mesmo tratamento que `relative_age` já dá pra isso (`<= 0` → `"hoje"`).

## Especificação técnica

```
modificar julius/domain/formatting.py      — weekday_phrase()
modificar tests/test_domain_formatting.py  — testes das faixas
```

### Padrão a seguir
- `relative_age` (mesmo arquivo): `today` injetável, faixas por `if`/`elif` em ordem crescente de dias, docstring explicando a fronteira com um comentário `ponytail:` se a faixa exigir uma decisão de arredondamento (não deveria precisar aqui, é só espelhar dias inteiros).
- Testes de faixa de `relative_age` em `tests/test_domain_formatting.py` já fixam `today` — seguir o mesmo padrão, nunca depender do dia em que a suíte roda.

## Testes obrigatórios

1. `test_weekday_phrase_today_and_yesterday` — 0 e 1 dia → `"hoje"`/`"ontem"`.
2. `test_weekday_phrase_this_week` — 2 a 7 dias → nome do dia sem `"passada"` (pelo menos dois pontos da faixa, ex.: 2 e 7).
3. `test_weekday_phrase_last_week` — 8 a 15 dias → nome do dia com `"passada"` (pelo menos dois pontos, ex.: 8 e 15).
4. `test_weekday_phrase_falls_back_to_relative_age_after_15_days` — 16 e 30 dias → igual a `relative_age(purchased_at, today=today)` pros mesmos valores.
5. `test_weekday_phrase_all_seven_names` — um `today`/`purchased_at` por dia da semana, conferindo os sete nomes exatos.
6. `test_weekday_phrase_invalid_input_is_empty_string` — string vazia e string não-data.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "^def weekday_phrase" julius/domain/formatting.py` existe.
- [ ] Nenhum outro arquivo muda além dos dois listados.

## Notas para o agente

- Não exponha um parâmetro de locale/idioma — este projeto é português fixo, mesma disciplina do resto de `domain/formatting.py`.
- `date.weekday()` começa em segunda (0); confira contra um dia real conhecido antes de fechar a lista de nomes, é o tipo de off-by-one fácil de errar silenciosamente.

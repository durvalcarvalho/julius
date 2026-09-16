# Handoff — smoke test da API DeepSeek (Julius AI)

Sessão: 2026-09-15. Script: `scratchpad/smoke_deepseek.sh` (roda T1–T4 contra
`JULIUS_AI_BASE_URL` = `https://api.deepseek.com`, modelo `deepseek-flash`).

## Bugs encontrados e corrigidos

### 1. `}` duplicado no corpo do curl (todos os testes davam HTTP 400)

`run()` montava o `-d` assim:

```bash
-d "{\"model\": \"$JULIUS_AI_MODEL\", $(tail -c +2 "$DIR/$t.json")}"
```

`tail -c +2` só remove o `{` de abertura do JSON gerado pelo Python — o `}` de
fechamento continua no final do arquivo. A linha acima ainda concatenava
*outro* `}` depois disso, gerando um JSON com chave sobressalente
(`"trailing characters at line 1 column N"`).

**Fix:** remover o `}` extra do fim da string `-d` (o `tail` já entrega o
fechamento correto).

### 2. T3 nunca terminava (`finish_reason: length`, `content` vazio)

Com `thinking` habilitado (comportamento default), o prompt do T3 (ENRICH —
6 produtos, regras mais longas) faz o modelo gastar todo o `max_tokens` só em
`reasoning_content` e nunca chega a escrever a resposta. Testado:

| `max_tokens` | resultado |
|---|---|
| 1200 (original) | reasoning consome 1199/1200, `finish_reason: length` |
| 3000 | reasoning consome os 3000, mesmo resultado |
| 8000 | reasoning consome os 8000, mesmo resultado |

Não é falta de budget — o reasoning não converge nesse prompt (looping ou
raciocínio desproporcional ao tamanho da tarefa).

**Fix:** desabilitar thinking explicitamente no corpo da requisição, como já
era feito no T2:

```json
"thinking": {"type": "disabled"}
```

Com isso T3 volta a `max_tokens: 1200` e responde em ~2s, `finish_reason:
stop`, JSON válido e correto (279 tokens totais).

## Estado final dos 4 testes

Todos passam com `finish_reason: stop` e `content` como JSON válido:

- **T1** (`{"ok": true}` simples, thinking default): reasoning presente, ok.
- **T2** (idem, thinking desabilitado): sem reasoning, ok.
- **T4** (MERGE — comparação de pares): thinking default funcionou sem
  estourar budget (299 reasoning tokens dentro de `max_tokens=500`).
- **T3** (ENRICH — catalogação de produtos): só funciona com thinking
  desabilitado; com thinking ligado, não converge em nenhum budget testado.

## Implicação para o código de produção (`julius/`)

Se o pipeline real de enrich (o mesmo prompt do T3, mais longo/estruturado)
usa `deepseek-flash` com thinking habilitado, é provável que sofra do mesmo
travamento — vale checar se o client em `julius/` já desabilita `thinking`
para essa chamada, ou se isso precisa ser adicionado. T4 (merge/comparação)
não mostrou esse problema, então pode não precisar do mesmo ajuste — mas não
foi testado com o volume real de pares do pipeline.

## Não investigado

- Por que thinking não converge especificamente no prompt ENRICH (não no
  MERGE) — pode ser o tamanho do system prompt, o formato de saída (lista com
  N objetos), ou algo específico do `deepseek-flash`. Não foi feito
  bisection do prompt para isolar a causa.
- Comportamento com volumes maiores que os do smoke test (6 produtos / 4
  pares) não foi verificado.

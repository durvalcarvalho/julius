# 174: smoke real da v2.7.1 e fechamento da documentação

> Fecha 170–173 contra o `deepseek-flash` de verdade (numa cópia do banco), do mesmo jeito que fechou a v2.7 original (ticket 169): mede se o tom, o veredito e o `max_tokens` novo funcionam, e atualiza `CLAUDE.md`/o índice com o resultado real, não com a expectativa.

## Contexto

Espelha o ticket 169. Depende de **170–173** (tudo).

## Escopo

### Dentro
- Rodar `services.suggestions.narrate` contra a API de verdade, numa cópia de `~/.local/share/julius/prices.db` (nunca o arquivo real — mesma disciplina do 169), para pelo menos:
  1. Um produto com 2 mercados e preços diferentes (o caso cebola/banana) — conferir veredito, blocos curtos, `weekday_phrase` no lugar da data.
  2. Um produto com 1 registro só — conferir que **não** aparece veredito.
  3. Um caso onde `_collapse_repeated_prices` (171) realmente colapsa algo real do catálogo, se existir; senão, anotar que não foi possível medir esse caminho contra dado real.
  4. Comparação de mercados (`compare_stores`) com 2+ grupos.
- `CLAUDE.md`: parágrafo/adendo de status **v2.7.1** (na mesma seção "Status", encostado no parágrafo do prompt v2) com o resultado real: `max_tokens` ficou curto/sobrou/adequado, o veredito apareceu certo, o tom bateu com o exemplo que o usuário deu.
- `docs/tickets/julius-bot/index.md`: nova sub-seção "Trilha v2.7.1 — humanização" com a tabela 170–173 e o estado.
- `docs/como-testar-o-bot.md`: uma nota curta (não um passo a passo novo inteiro) apontando que o roteiro de smoke da v2.7 (passos 16–20) agora também cobre veredito/blocos curtos/dia da semana/indicador de digitação — só ajustar o texto onde já descreve o que esperar, não duplicar o roteiro.

### Fora
- Testar o indicador de "digitando..." de verdade — isso só existe dentro do Telegram real (é visual, não aparece em `ai_calls.jsonl`); fica pro roteiro manual do usuário, não pro smoke de código.
- Qualquer ajuste de código além do que o smoke revelar como bug de fiação (mesma regra dos tickets 162/169).

## Requisitos

### Funcionais
- Nenhuma alegação de tom/qualidade no `CLAUDE.md` sem o texto real gerado no smoke pra sustentar — cite um trecho real, como o 169 já fez.
- Se `max_tokens = 260` (172) cortar uma resposta no meio (`finish_reason` truncado, visível em `ai_calls.jsonl`), ajustar o valor aqui mesmo e documentar o número que funcionou — mesma regra do 169 sobre corte de tamanho.

### Validação e erros
- Banco real (`~/.local/share/julius/prices.db`) tem que continuar com a mesma contagem de linhas em `prices` depois do smoke — é só leitura + chamada de IA, nunca escrita no banco de verdade.

## Especificação técnica

```
modificar CLAUDE.md
modificar docs/tickets/julius-bot/index.md
modificar docs/como-testar-o-bot.md
```

### Padrão a seguir
- Ticket 169 é o precedente exato: script de smoke descartável (scratchpad, não versionado), cópia do banco, limpeza dos arquivos temporários no final.

## Testes obrigatórios
- Nenhum teste automatizado novo (documentação + medição manual). `.venv/bin/pytest -q` continua verde, suíte inalterada.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inalterada).
- [ ] `grep -n "v2.7.1" CLAUDE.md` existe.
- [ ] `docs/tickets/julius-bot/index.md` lista 170–173 com estado atualizado.
- [ ] Banco real intacto (mesma contagem de `prices` antes/depois, conferida e citada no resultado).

## Notas para o agente

- Copie o texto real que a IA devolveu no smoke pro `CLAUDE.md`, como o 169 fez com o exemplo da banana — não parafraseie.
- Se o veredito vier em contexto errado (ex.: aparecer com 1 registro só, ou não aparecer com 2+), isso é achado do prompt (172), não bug de fiação — anote e, se for pequeno, ajuste o prompt aqui mesmo com a mesma disciplina de versionar (`PROMPT_VERSIONS["persona"]` sobe pra `"4"` se o texto mudar).

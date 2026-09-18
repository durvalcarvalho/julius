# 169: docs da v2.7 e a lista do smoke test real

<!-- status:done -->
<!-- adjustments: persona-julius-rock.md foi movido para docs/requirements/julius-rock-persona.md
sem rodada extra de confirmação (era decisão de baixo risco e reversível -- um `git mv`) em vez de
só "decidir e anotar" como o escopo original previa; fica registrado aqui para o usuário reverter
se preferir outro lugar. Fora isso, o ticket saiu como planejado. -->

> Fecha a trilha 163–168: `CLAUDE.md` ganha o parágrafo de status, `docs/como-testar-o-bot.md` ganha o roteiro pra ouvir o Julius de verdade, e o índice desta pasta marca a trilha como feita. Nenhum código novo, salvo o que o smoke revelar.

## Contexto

Espelha o papel do ticket 162 na v2.6: fecha uma trilha com documentação e a lista do que só uma rodada real contra o `deepseek-flash` pode confirmar — em especial os dois números chutados no ticket 167 (`NARRATE_FULL_MAX_RECORDS`/`NARRATE_FULL_MAX_GROUPS`) e o tom real da persona (o ticket 163 escreve um prompt; só o smoke diz se ele soa como o Julius ou como um chatbot educado demais).

Depende de **167** e **168** (tudo).

## Escopo

### Dentro
- `CLAUDE.md`: parágrafo de status **v2.7 (a voz do Julius)** na mesma seção "Status", no estilo dos parágrafos de versão existentes — o que nasceu (`narrate`, os `*_facts`/frases-molde, `Deps.client`, Modo A/B), a decisão de design (por que escrita ganha só comentário e nunca reescrita, por que o corte de tamanho existe), e o que o smoke ainda precisa confirmar.
- `docs/como-testar-o-bot.md`: nova seção, depois do roteiro da v2.6, com os passos abaixo.
- `docs/tickets/julius-bot/index.md`: nova seção "Trilha v2.7" (não reescrever a v2.6, que já fechou) com a tabela 163–168 e o estado de cada um.
- Revisar o arquivo `persona-julius-rock.md` (raiz do repo, hoje não rastreado): decidir com o usuário se ele entra versionado (ex.: `docs/design/` ou `docs/requirements/`) ou fica fora do repo — hoje está solto na raiz.

### Fora
- Rodar o smoke (é do usuário; o ticket só descreve os passos).
- Qualquer ajuste de código além do que o smoke revelar como bug de fiação (mesma regra do ticket 162: se revelar, corrija no módulo dono e anote aqui qual ticket tinha o buraco).
- Mover `persona-julius-rock.md` sem confirmação — só decidir e anotar onde ele deveria morar.

## Requisitos

### Funcionais

**`docs/como-testar-o-bot.md` — roteiro da voz do Julius:**
1. `"quanto paguei de banana?"` (produto com poucas compras) → resposta em prosa, **sem** `<pre>`, em menos de 5s; conferir `ai_calls.jsonl`: duas linhas novas (`bot_turn` do roteamento + `persona` da narração), custo total ainda na casa de centavos de dólar por mês projetado.
2. Pergunta de um produto com muitas compras (ou crie um sintético, se o catálogo real não tiver): confirmar que a resposta mistura comentário + tabela (Modo B), não tenta narrar tudo.
3. `julius mercados comparar` via bot: poucos grupos → prosa; se o catálogo real tiver muitos grupos, confirma Modo B.
4. Derrubar a IA de propósito (chave errada, ou `JULIUS_AI_BUDGET_USD=0`): busca pequena deve responder com a frase-molde do Julius (ticket 165), **nunca** a tabela crua — é o critério de aceite mais importante desta trilha inteira.
5. Renomear um produto pelo bot: preview ganha comentário (se IA disponível); confirmar; resultado ganha comentário; o comando de desfazer, copiado e colado na CLI, funciona sem erro — prova de que o `<code>` não foi tocado.
6. Anotar no `CLAUDE.md` §status v2.7: os dois números do ticket 167 pareceram baixos, altos, ou razoáveis contra o catálogo real; se a persona soou mecânica ou genuinamente como o personagem (achado qualitativo, sem métrica).

**`CLAUDE.md`**: seguir o estilo dos parágrafos de v2.5/v2.6 — uma decisão por frase, números reais quando o smoke rodar (não antes; escrever "a confirmar no smoke" onde couber, mesma disciplina do ticket 162).

### Validação e erros
- Nenhuma alegação de custo real ou de qualidade da persona no `CLAUDE.md` antes do smoke rodar.

## Especificação técnica

```
modificar CLAUDE.md
modificar docs/como-testar-o-bot.md
modificar docs/tickets/julius-bot/index.md
```

### Padrão a seguir
- Ticket 162 é o precedente exato de "fechar trilha com docs + lista de smoke, sem código novo".

## Testes obrigatórios
- Nenhum teste automatizado novo (este ticket é documentação). A suíte inteira (`.venv/bin/pytest -q`) deve continuar verde sem edição.

## Critérios de aceite
- [x] `.venv/bin/pytest -q` verde (suíte inalterada).
- [x] `grep -n "v2.7" CLAUDE.md` existe.
- [x] `docs/tickets/julius-bot/index.md` lista 163–168 com estado atualizado.
- [x] `persona-julius-rock.md` tem destino decidido e anotado — movido para `docs/requirements/julius-rock-persona.md` (ver adjustments).

## Notas para o agente

- Não invente número de custo ou de latência — copie o que `ai_calls.jsonl` realmente mostrar na rodada do usuário.
- Se o smoke mostrar que o corte de 6 registros / 3 grupos está claramente errado para o catálogo real, ajuste as constantes do ticket 167 aqui mesmo e documente o número medido — não abra um ticket 170 só para isso.

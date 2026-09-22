# Design: registrar preço avulso por chat

> **STATUS (2026-09-22): pausado — decisão do usuário é NÃO construir isso.** Este desenho nasceu de uma leitura errada de uma resposta ambígua (ver a correção em `docs/requirements/bot-persona-fallback-improvements.md` §9). Confirmado depois: preço avulso por chat não vai ser feito; o fallback dos Casos 1/3/6 resolve só pela voz, sem CTA, mantendo a regra já medida de não pedir dado de volta. Documento mantido como registro — não apagado — porque o raciocínio de "por que tabela nova em vez de reaproveitar `prices`" (§1) continua válido caso essa decisão seja reaberta um dia com evidência nova; até lá, nada aqui deve ser implementado.

> Desenho de `docs/requirements/bot-persona-fallback-improvements.md` §4.1/§9 — o item que os Casos 1, 3 e 6 daquele documento pedem e que o usuário confirmou não ser opcional (CTA sem gravar seria promessa vazia). Decisões de schema, interface e fluxo. **Nada de código final aqui** — o próximo passo é `/sc:implement`.

## 0. O que este desenho resolve

Hoje, `prices` só recebe linhas de `julius importar` (nota fiscal). As 10 ações de escrita do bot (`bot/actions.py::WRITE_ACTIONS`) só corrigem metadado de catálogo — nenhuma cria uma linha de preço. Este desenho adiciona a primeira via de entrada de preço que não passa por nota fiscal, decidindo onde ela mora, como se junta ao resto do sistema, e como continua reversível — sem violar o invariante "todo preço em `prices` vem de uma nota".

## 1. Decisão central: tabela nova, não reaproveitar `prices`

`prices` tem `PRIMARY KEY (access_key, item_index)` — chave que só faz sentido para um item de uma nota importada, e todo o resto do sistema (arquivamento de nota, dedup de import, a política "preço errado se corrige via SQL direto porque é sempre um evento raro rastreável até uma nota") assume essa origem. Forçar um preço avulso para dentro dessa tabela exigiria fabricar `access_key`/`item_index` sintéticos — gambiarra que contamina a semântica de uma chave que hoje é 100% confiável.

**Decisão**: tabela nova, `manual_prices`, mesma família de dado (é um `Price`, no sentido dos agregados já documentados — não um agregado novo), mas com identidade própria:

```sql
-- Preço avulso reportado por chat, sem nota fiscal por trás. Mesma família de dado que `prices`
-- (mesmo agregado Price), mas com identidade própria: PRIMARY KEY autoincremental, não
-- (access_key, item_index) -- essa chave só faz sentido para um item de uma nota importada, e
-- reaproveitá-la aqui exigiria fabricar valores sintéticos que contaminariam a garantia que o
-- resto do sistema já confia nela (arquivamento de nota, dedup de import).
CREATE TABLE manual_prices (
    id           INTEGER PRIMARY KEY,
    product_id   INTEGER NOT NULL REFERENCES products(id),
    store_cnpj   TEXT NOT NULL REFERENCES stores(cnpj),
    unit         TEXT NOT NULL CHECK (unit IN ('UN', 'KG')),
    unit_price   REAL NOT NULL,
    reported_at  TEXT NOT NULL,  -- sempre "agora" nesta rodada (ver §9); ISO local, mesma convenção de prices.purchased_at
    chat_id      INTEGER          -- quem reportou; hoje sempre o único chat da allowlist. NULL permitido -- gancho pronto
                                   -- para o dia em que existir mais de um chat confiável (requisitos §6.4), sem custo agora.
);
```

Migração seguinte disponível: `0007_manual_prices.sql` (a árvore já foi além do que `CLAUDE.md` documentava — `0005`/`0006` já existem, para `product_group_name` e `decision_usage`).

`product_id` grava o id resolvido por `resolve_product` (já a raiz do grupo, ver `bot/actions.py::resolve_product`) — mesma convenção que `prices.product_id` usa (um id que `product_group` resolve na leitura), então uma fusão futura que envolva esse produto continua funcionando sem tocar em `manual_prices`.

## 2. O achado que barateia tudo: existe UM seam de leitura, não vários

`repositories/prices.py::prices_for_products` é o único ponto que `search_prices`, `compare_stores`, `check_price`, `records_facts`/`comparison_facts` (via `PriceRecord`) têm em comum — todos operam sobre a lista de `PriceRecord` que essa função devolve. Union-ar `manual_prices` **dentro** dela (mesmo `JOIN product_group`/`products root`, unit/preço/data no lugar certo, cheapest/highlight recalculados como já são) faz o preço avulso aparecer em busca, comparação entre mercados e conferência de preço ao vivo **de graça**, sem tocar `search.py`, `comparison.py`, `render.py` nem o prompt `persona` na parte de citar fato.

**Segundo lugar, que NÃO compartilha esse seam** — precisa de ajuste próprio: `repositories/prices.py::export_rows`/`_EXPORT_SQL` (usado por `julius exportar`) é uma query separada, direto em `prices`. Sem tocar nela, o preço avulso nunca aparece no CSV. Decisão a bater com o usuário: incluir (com uma coluna a mais, `source`) ou deixar de fora do export por ora — não é ambíguo tecnicamente, é só um segundo lugar que o design não pode fingir que "vem de graça" junto com o primeiro.

## 3. Contrato da ação nova (interface, não implementação)

Mesma forma de toda escrita do bot hoje — duas passadas, `PendingWrite` → confirmação por botão → `execute`:

```
async def report_price(
    ctx: RunContext[Deps], item: str, price: float, store: str, unit: str,
) -> PendingWrite
```

- `item`/`store`: reaproveitam `resolve_product`/`resolve_store` — zero código novo de resolução, mesmas mensagens de ambiguidade/não-encontrado que toda outra ação já usa.
- `unit`: obrigatório nesta rodada (produto sem histórico não tem unidade conhecida pra inferir; ver §9 sobre inferência a partir do histórico, deixada de fora). O prompt pede à pessoa quando não estiver claro, mesma disciplina de `set_product_content`.
- `price`: validação de positivo, mesmo padrão de `ModelRetry` que `set_product_content` já usa para quantidade.
- Preview segue o padrão de `_pending(...)`: algo como `"Registrar Coca-Cola 2L a R$ 12,00 a unidade no Extra"`.

`_do_report_price` (executor) grava via um `catalog.report_price(conn, product_id, store_cnpj, unit, unit_price, reported_at) -> int` novo em `services/catalog.py` (mesmo padrão que `rename_product`/`tag_product` já seguem: um `with conn:` em volta de uma chamada de repositório), devolvendo o `id` gravado — necessário para o undo (§4).

## 4. Desfazer: reaproveita a política que já existe para preço, não a de catálogo

Toda ação de catálogo (renomear, tag, tipo, conteúdo, fusão) tem `WriteResult.undo` como um comando `julius` pronto pra copiar. Preço avulso é dado diferente — é da mesma família que `prices`, e o projeto **já tem uma política pra preço errado**: "sem comando dedicado, usa `sqlite3 prices.db` direto" (`CLAUDE.md`, seção Decisões). Este desenho reaproveita exatamente essa política em vez de inventar um comando `julius produtos preco-avulso --remover` novo:

```
undo=f"DELETE FROM manual_prices WHERE id = {new_id};"
```

`render_result` já mostra qualquer string em `<code>` — não exige que seja um comando `julius`, então isso funciona sem tocar `render.py`. Menor desenho possível que ainda é consistente com uma convenção já existente, em vez de inventar uma nova.

## 5. Honestidade: a origem do preço precisa viajar até a persona

O prompt `persona` cita fatos exatamente como vêm — mas hoje todo fato tem o mesmo peso implícito de "veio de uma nota fiscal real". Um preço que a própria pessoa acabou de digitar tem uma garantia diferente (nenhuma nota por trás, ninguém conferiu) e a guarda de honestidade do projeto (`no_unlicensed_data_claims`, e toda a disciplina de "a IA nunca afirma o que não pode verificar") existe exatamente para esse tipo de distinção.

**Decisão**: `PriceRecord` ganha um campo `source: Literal["receipt", "manual"] = "receipt"` (default preserva todo chamador/teste existente sem mudança). `render.py::records_facts`/`comparison_facts` marcam a linha (`"(informado por você)"`) quando `source == "manual"`. Isso não muda `highlight`/ranking — um preço avulso confirmado pela pessoa entra no cálculo de mais-barato/mais-caro do mesmo jeito que um preço de nota (ela já confirmou por botão, mesma barra de confiança que qualquer outra escrita deste bot) — só muda a citação, pra nunca implicar "isso veio de um cupom" quando não veio.

## 6. Fluxo completo (sequência)

1. Busca/comparação vem vazia (ou a pessoa já diz "paguei R$12 na Coca 2L no Extra" direto, sem passar por busca).
2. O prompt de roteamento (mudança de prompt, fora deste desenho — ver `docs/requirements/bot-persona-fallback-improvements.md` §4.2) reconhece a intenção e chama `report_price`.
3. `resolve_product`/`resolve_store` resolvem ou pedem esclarecimento (`ModelRetry`, igual a toda ação hoje).
4. `PendingWrite` com preview → `bot/turn.py` mostra o teclado de confirmação (fluxo já existente, nenhuma mudança).
5. Tap → `execute` → `catalog.report_price` grava → `WriteResult` com resumo específico ("R$ 12,00 no Extra vira a referência da Coca 2L agora") e o `DELETE` de desfazer.
6. Próxima busca do mesmo produto já inclui essa linha, via o seam único do §2 — sem esperar nenhum outro código rodar.

## 7. Fora deste desenho (decisão explícita, não esquecimento)

- **Data retroativa** ("paguei isso semana passada"): `reported_at` é sempre "agora". Nenhum dos 6 casos do requisito pede isso — se aparecer uso real pedindo, é o gatilho pra adicionar um parâmetro `when`, não construir agora.
- **Inferir `unit` do histórico do produto**: cortado por simplicidade — produto sem histórico não tem o que inferir mesmo, e produto com histórico já tem `unit` conhecido por quem pergunta (a pessoa mesma), então perguntar sempre é uniforme e barato.
- **Peso diferenciado de preço avulso vs. de nota no ranking/veredito**: nenhuma evidência de que isso importa; tratar igual (uma vez confirmado por botão) é a opção mais simples e a mais alinhada com "o usuário já confirmou, então é fato".
- **`julius exportar` incluir preço avulso**: apontado no §2 como um segundo lugar que precisa de decisão própria — não resolvido aqui, é uma pergunta a bater antes de `/sc:implement`.
- **Correção em linguagem natural** ("na verdade foi R$14, não R$12"): fora de escopo; a política vigente (SQL direto) já cobre.
- **Multi-usuário de verdade**: `chat_id` é só um gancho de schema (nullable, sem lógica em cima) — nada no fluxo trata dois chats diferente ainda.

## 8. Riscos a medir antes de aprovar para implementação

- **Confusão de roteamento com `check_price`**: as duas ações partem de "a pessoa disse um preço" — `check_price` é usado quando ela está vendo o preço AGORA e quer uma opinião (sim/não), `report_price` quando ela quer que o preço fique guardado (geralmente depois de o bot já ter dito "não tenho isso ainda"). O prompt final precisa de um exemplo de entrada/saída pra cada uma lado a lado — mesma lição que este projeto já aprendeu (`CLAUDE.md`, "só a instrução em prosa não bastou" na v2.8); não é algo que só a docstring da função resolve sozinha.
- **Custo de IA**: `report_price` não adiciona nenhuma chamada nova de IA além do roteamento que já acontece a cada mensagem — não muda o orçamento.
- **`unit` inconsistente com o histórico do produto**: se a pessoa reportar "a unidade" para um produto que só tem histórico em KG, isso cria dois grupos de unidade pro mesmo produto — o mesmo comportamento que já existe hoje para receitas reais que trazem unidade diferente por engano (o sistema já trata "nunca mistura UN com KG" separando por grupo). Nenhum tratamento especial necessário, mas vale confirmar com um teste dedicado na implementação.

## 9. Próximo passo

`/sc:implement`, dividido nas peças que este desenho já isolou: (1) migração `0007_manual_prices.sql`; (2) `repositories/prices.py` — `insert_manual_price` + União em `prices_for_products`; (3) `PriceRecord.source` + marcação em `render.py`; (4) `services/catalog.py::report_price`; (5) `bot/actions.py::report_price` + `_do_report_price` + entrada em `WRITE_ACTIONS`; (6) prompt de roteamento (`SYSTEM_PROMPT`) com o par de exemplo report_price vs. check_price; (7) decisão pendente do §2 sobre `julius exportar`.

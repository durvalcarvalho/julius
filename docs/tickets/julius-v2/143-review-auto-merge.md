# 143: `_review` — funde o que a IA confirmou e manda conferir

> O padrão se inverte: em vez de imprimir comandos `fundir` para o usuário rodar, o sistema funde e avisa.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §4.4. Requisitos RF2–RF6 e a medição F2/F3 (19 candidatos → a IA confirma 2, ambos corretos, e rejeita o `Alho ≈ Pão de Alho` que antes vinha com 1,00).

Depende de **141** (o `desfundir` existe e está testado — RF7) e **142** (o guarda de conteúdo).

## Escopo

### Dentro
- `julius/cli/_review.py`: o bloco de duplicatas passa a fundir e notificar.
- `tests/test_cli_review.py`.

### Fora
- Qualquer corte de confiança (RF2: o gatilho é `same_product`, sem limiar).
- Escolher o sobrevivente por outra regra que não o menor id (Q1).
- Perguntar antes de fundir, inclusive com `--sim`: o pedido do usuário é "faz e me avisa".
- Fundir produtos que a IA não confirmou (RF5: nada acontece e nada é impresso).

## Requisitos

### Funcionais

- Ordem dentro de `review_products` (a atual, com o bloco de duplicatas trocado):
  `propor → tabela → passada automática → log → resumo → laço de conteúdo → FUNDIR → pendentes`.
- Para cada par que `judge_duplicates` confirmou:
  1. **sobrevivente = menor id**, absorvido = o outro (Q1);
  2. `catalog.merge_inheritance` **antes** de fundir (depois, a informação já está derivada e não se sabe mais o que foi herdado);
  3. `catalog.merge_products(absorvido, sobrevivente)`;
  4. uma `AppliedAction(sobrevivente, "merge", None, str(absorvido))` por fusão, gravada por `_log_actions` como qualquer outra;
  5. falha de uma fusão (`ValueError`/`LookupError`) não interrompe as outras nem muda o código de saída.
- A notificação, que é requisito e não cortesia:

```
Fundidos automaticamente (confira):
  33 ← 80  Banana prata ≈ Banana Prata Extra União — mesma variedade; Extra União é marca/fornecedor
           o grupo herdou o conteúdo 0,4 KG do produto 80
           desfazer: julius produtos desfundir 80
```
  - a linha de herança sai **só** quando `merge_inheritance` devolveu algo (F17: é o alerta que impede um conteúdo herdado errado de passar invisível);
  - o `rationale` é o que a IA escreveu, sem reescrita;
  - o comando de desfazer é o mesmo que `_undo_command` produz, para não existirem duas grafias.
- Nenhuma fusão: nada é impresso (nem "nenhuma duplicata").
- `--sim` **não** desliga a fusão: ele significa "não perguntar nada", e fundir não pergunta.

### Validação e erros
- Sem IA disponível, sem candidatos, ou nenhum veredito positivo: o bloco não faz nada e não imprime.
- A fusão nunca altera o código de saída da revisão.

## Especificação técnica

```
modificar julius/cli/_review.py
modificar tests/test_cli_review.py
```

### Padrão a seguir
- `judge_duplicates` já devolve só os pares com `same_product` verdadeiro — não refiltre por `confidence`.
- `_log_actions` e `_undo_command` já existem e já tratam `"merge"` (141).
- A CLI é o composition root: quem funde é `catalog`, a CLI só ordena e imprime.

## Testes obrigatórios

1. `test_review_merges_confirmed_duplicate` — IA confirma um par → depois da revisão, `produtos listar` mostra um produto só e o histórico dos dois está junto.
2. `test_review_merge_keeps_the_lowest_id` — o par (80, 33) → sobrevive o 33.
3. `test_review_merge_prints_confirmation_request_and_undo` — a saída traz "confira", o `rationale` e `julius produtos desfundir 80`.
4. `test_review_merge_announces_inherited_content` — alvo sem conteúdo, absorvido com → a saída diz que o grupo herdou, citando o produto de origem.
5. `test_review_merge_logs_the_action` — `actions.jsonl` tem a linha `field="merge"` com `undo` igual ao comando impresso.
6. `test_review_does_not_merge_unconfirmed_pair` — IA responde `same_product: false` → nada funde, nada é impresso.
7. `test_review_merge_survives_a_failing_merge` — um par válido e um par cujo `merge_products` levanta (ex.: produto já fundido) → o válido funde, código de saída 0.
8. `test_review_with_sim_still_merges` — `--sim` funde igual.
9. `test_review_prints_nothing_when_no_duplicate` — nenhuma linha sobre duplicatas.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -n "julius produtos fundir" julius/cli/_review.py` **vazio** — o comando não é mais impresso para o usuário rodar.
- [ ] `grep -n "confidence" julius/cli/_review.py` vazio — nenhum limiar entrou.
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente

- **`produtos comparar ID_A ID_B` continua só opinando** e imprimindo o `fundir` — é o usuário pedindo por um par específico, e não muda neste ticket.
- Não acrescente teto de fusões por rodada: `MAX_DUPLICATE_PAIRS = 20` já limita os candidatos, e a IA confirmou 2 de 19 nas duas medições.
- Se a IA confirmar um par obviamente errado na sua execução manual, **não** conserte com heurística nem mexa no prompt: desfunda, e anote no ticket 146. O desfazer barato é a mitigação escolhida.

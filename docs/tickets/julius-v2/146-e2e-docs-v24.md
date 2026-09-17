# 146: e2e da v2.4, rodada real e documentação

> Fecha a fase: o ciclo fundir → consultar → desfundir num teste, a execução real contra cópia do banco, e os documentos deixando de dizer que fundir é irreversível.

## Contexto

Mesmo papel dos tickets 114 (v2), 130 (v2.2) e 136 (v2.3). Fontes: `docs/design/merge-and-unit-price-v2.4.md` e `docs/requirements/auto-merge-and-unit-price-v2.4.md`.

Depende de **137–145**.

## Escopo

### Dentro
- `tests/test_e2e.py`: um teste do ciclo completo da v2.4.
- `CLAUDE.md`: "Status", "Identidade de produto e busca", "Camada opcional de IA", "Armazenamento" (migração 0004), "Estrutura de pacote", "CLI", "Fora do escopo", "Decisões".
- `README.md`: `fundir`/`desfundir`, o que a revisão funde sozinha, a linha de resposta em `consultar`.
- `docs/tickets/julius-v2/index.md`: 137–146 como `feito`.
- **A rodada real** contra uma cópia do banco de produção, com a chave do usuário.

### Fora
- Qualquer mudança de comportamento em `julius/`. Se algo não funcionar, o ticket de origem ficou incompleto: **pare e anote**.
- Reprocessar o banco real a partir dos HTMLs: é plano B medido (F14/F15), não ação desta fase.
- Tratar as três fusões antigas (F13): estão corretas e não recebem migração.

## Requisitos

### Funcionais

- **Teste e2e** `test_v24_merge_cycle`, com `ScriptedLlmClient` cobrindo `enrich`, `packaging` e `merge`:
  1. importa dois fixtures reais de lojas diferentes;
  2. roda `produtos revisar` com a IA confirmando um par → confere que fundiu, que a saída pediu conferência e trouxe o `desfundir`, e que `actions.jsonl` tem a linha `field="merge"`;
  3. `consultar` traz o histórico dos dois produtos sob **um** nome;
  4. confere que **nenhuma linha de `prices` mudou de `product_id`** (a query de contagem antes/depois é idêntica);
  5. `produtos desfundir <absorvido>` → os dois voltam a aparecer separados, com seus próprios atributos, e o produto que tinha herdado conteúdo volta a não ter;
  6. roda `produtos revisar` de novo e confere que o par voltou a ser candidato (nada de estado escondido);
  7. confere que um par com conteúdo divergente **não** é fundido nem sugerido.

- **Rodada real, obrigatória antes de fechar:**
  ```
  cp ~/.local/share/julius/prices.db /tmp/v24.db
  JULIUS_DB=/tmp/v24.db julius produtos revisar
  JULIUS_DB=/tmp/v24.db julius consultar agua
  ```
  Registrar neste ticket quatro números medidos: quantos candidatos sobraram depois do guarda de conteúdo (esperado **15**, contra 19), quantas fusões automáticas aconteceram (esperado **2**: Banana e Uva), quantas linhas `julius consultar agua` passou a mostrar (esperado **4**, contra 9) e o custo em US$. Conferir que a frase "Mais barato por litro" cita a Indaiá 1,5L a R$ 2,46/L.

- **`CLAUDE.md`** — o que precisa mudar de fato:
  - **Status**: fase v2.4, contagem real de testes (medir, não estimar).
  - **Identidade de produto e busca**: a seção afirma que "fusão automática foi rejeitada por medição" e que `merge_products` "apaga a linha de origem; não há desfazer". As duas frases ficaram falsas. Registrar: a medição foi **refeita contra o catálogo curado** (19 candidatos → 2 confirmados, ambos corretos, e o `Alho ≈ Pão de Alho` rejeitado), e a fusão passou a ser um estado reversível.
  - Registrar os **dois filtros medidos e reprovados**: corte de confiança (acertos com 0,70/0,80, falso positivo com 1,00) e `kind` igual (12 dos 19 candidatos, incluindo Água c/gás ≈ s/gás e Pepsi ≈ Guaraná) — é o que impede a próxima sessão de tentar de novo. E o filtro que **funcionou**: conteúdo divergente, 4 de 4 falsos positivos.
  - **Camada opcional de IA**: a frase "a IA grava o reversível, nunca o irreversível" continua valendo — mas fusão saiu da lista de irreversíveis. Registrar a condição que mudou: o desfazer existe (ticket 141) e o erro é visível (o grupo aparece com um nome só em `produtos listar`).
  - **Armazenamento**: a migração 0004, a coluna e a view, com a nota de que um ciclo trava a resolução e por isso a guarda é na escrita.
  - **Preço por conteúdo**: a herança de conteúdo na fusão é derivada, não gravada, e por isso desfundir a reverte sozinho.
  - **CLI**: `desfundir`; `fundir` sem confirmação e sem "irreversível"; a linha de resposta em `consultar`.
  - **Fora de escopo**: acrescentar "corte de confiança para fusão", "filtro de fusão por tipo", "densidade por produto" e "reatribuir `prices.product_id` numa fusão".
- **`README.md`**: `fundir` deixa de ser irreversível (e a seção que diz "Fundir: irreversível — por isso pede confirmação" muda), `desfundir` aparece, e a revisão passa a fundir sozinha com pedido de conferência.

### Validação
- A contagem de testes no `CLAUDE.md` é o número que `.venv/bin/pytest -q` imprime.
- Nenhuma afirmação sobre a precisão da fusão além do medido: 2 de 2 acertos numa amostra de 19 candidatos, reproduzida duas vezes no mesmo catálogo.

## Especificação técnica

```
modificar tests/test_e2e.py
modificar CLAUDE.md
modificar README.md
modificar docs/tickets/julius-v2/index.md
```

### Padrão a seguir
- O e2e usa `CliRunner` com `JULIUS_DB` em `tmp_path` e os helpers `_run`/`_import`/`copied_fixtures`/`restore_fixture` — reaproveite.
- O estilo do `CLAUDE.md` é prosa densa com o porquê e números medidos. Acrescente medição, não adjetivo.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; o número final é o que está no `CLAUDE.md`.
- [ ] `git diff --stat julius/` **vazio** neste ticket.
- [ ] `grep -rn "Irreversível\|não dá para desfazer\|fusão automática foi rejeitada" CLAUDE.md README.md` **vazio**.
- [ ] `grep -n "conteúdo divergente" CLAUDE.md` encontra o filtro que funcionou.
- [ ] `grep -n "ciclo" CLAUDE.md` encontra a nota sobre a guarda.
- [ ] A rodada real foi executada contra cópia e os quatro números estão registrados.

## Rodada real (executada em 2026-09-17, contra cópias do banco de produção)

Duas execuções, porque o banco curado já não tem fila:

```
cp ~/.local/share/julius/prices.db <cópia>.db
JULIUS_DB=<cópia>.db julius produtos revisar --sim     # fila de 2 produtos: nenhum par no escopo
JULIUS_DB=<reprocessado>.db julius produtos revisar --sim   # 108 produtos pendentes: a curadoria inicial
```

A segunda é a informativa: o banco reprocessado dos 6 HTMLs (F14) põe todos os produtos na fila, que é o cenário em que a fusão automática de fato acontece.

| Número | Medido | Esperado no ticket |
|---|---|---|
| Candidatos depois do guarda de conteúdo | **15** (contra 19) | 15 |
| Fusões automáticas | **4**, todas corretas | ~2 (Banana e Uva) |
| Linhas de `consultar agua` | **4** (contra 9) | 4 |
| Custo | **US$ 0,0100** | — |

Aplicado na mesma passada: 104 nomes, 108 categorias, 72 conteúdos, 107 tipos.

**As quatro fusões, e por que são a melhor evidência desta fase:**

```
  4 ← 8   Sacola reutilizável ≈ Sacola reutilizável — mesmo produto, sem distinção de marca ou tamanho
  5 ← 82  Tomate italiano ≈ Tomate italiano União — mesma variedade; União é fornecedor
 11 ← 81  Cebola ≈ Cebola União — mesma variedade; União é fornecedor
 39 ← 65  Banana prata ≈ Banana prata extra União — mesma variedade; extra e União são qualificadores
```

**Três das quatro (Tomate, Cebola, Sacola) são exatamente as fusões que o usuário já havia feito à mão** no banco de produção (F13): o sistema reproduziu sozinho o julgamento humano registrado, sem ter acesso a ele. A quarta (Banana) é o par que as duas medições anteriores já tinham apontado como correto. **Nenhum falso positivo.** O esperado no ticket era ~2 porque a medição anterior rodou contra o catálogo onde as três já estavam fundidas — não havia par para achar.

**As invariantes conferidas na mesma rodada:** as 132 linhas de `prices` continuam com os mesmos `product_id` (nenhuma reatribuída), 104 produtos visíveis de 108 (4 absorvidos, nenhum apagado), e `julius produtos desfundir 82` respondeu *"Produto 82 'Tomate italiano União' voltou a ser separado."*.

**A frase da frente B, no dado real:** `Mais barato por litro: Água mineral Indaiá 1,5L a R$ 2,46/L — contra R$ 3,58/L de Água Crystal com gás 500ml.`

## Notas para o agente
- O ponto mais importante da documentação é **por que a rejeição da fusão automática caiu**: não foi mudança de opinião, foi a medição refeita contra um catálogo que a v2.3 curou. Sem isso, a próxima sessão vai ler o histórico e achar que alguém ignorou a decisão anterior.
- Registre também a regra que generaliza: **a IA pode gravar sozinha o que o usuário consegue ver que está errado e desfazer com um comando.** Fusão passou a cumprir as duas metades; conteúdo inferido por costume de varejo continua cumprindo só a primeira.
- Se a rodada real fundir algo errado, anote o par e desfunda. Não conserte com heurística nem mexa no prompt.

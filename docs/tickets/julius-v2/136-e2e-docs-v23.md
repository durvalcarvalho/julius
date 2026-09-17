# 136: e2e da v2.3, rodada real e sincronização de documentação

> Fecha a fase: um teste do ciclo novo, a execução real contra uma cópia do banco de produção, e os documentos contando a verdade — inclusive o porquê de a intuição nunca gravar.

## Contexto

Mesmo papel dos tickets 114 (v2) e 130 (v2.2). Fontes: `docs/design/review-scope-v2.3.md` e `docs/requirements/review-scope-v2.3.md`.

Depende de **131–135** (é o último da trilha).

## Escopo

### Dentro
- `tests/test_e2e.py`: um teste do ciclo completo da v2.3.
- `CLAUDE.md`: "Status", "Camada opcional de IA", "Identidade de produto e busca", "Preço por conteúdo", "Estrutura de pacote", "CLI", "Dicas de uso" (se algo mudou), "Design de testes".
- `README.md`: `produtos revisar` (o que pergunta e o que não pergunta), `--sim`, a pergunta de conteúdo.
- `docs/tickets/julius-v2/index.md`: marcar 131–136 como `feito`.
- **A rodada real** contra uma cópia do banco de produção, com a chave do usuário.

### Fora
- Qualquer mudança de comportamento em `julius/`. Se algo não funcionar, o ticket de origem ficou incompleto: **pare e anote**, não conserte aqui.
- Reescrever as seções antigas do `CLAUDE.md` que usam vocabulário em português: o código é a fonte da verdade dos nomes.
- Mexer no banco real do usuário. A rodada é contra **cópia**.

## Requisitos

### Funcionais

- **Teste e2e** `test_v23_review_cycle` (ou nome equivalente), com `ScriptedLlmClient` cobrindo `enrich`, `packaging` e `merge`:
  1. importa dois fixtures reais;
  2. roda `julius produtos revisar` com TTY simulado (`monkeypatch` em `_is_interactive`), com a IA devolvendo: um produto com conteúdo no rótulo, um produto sem conteúdo e vendido por UN, e um produto vendido por KG sem conteúdo;
  3. confere que **o de rótulo foi gravado sem pergunta**, que **o de KG não foi perguntado**, e que **o de UN gerou a pergunta com os candidatos** do `packaging`;
  4. responde `1` e confere o conteúdo gravado e a linha em `actions.jsonl` com o comando de desfazer;
  5. roda de novo e confere que o produto já resolvido **não** volta a ser perguntado e que o pulado volta;
  6. confere que a tabela mostra a descrição do cupom e o nome legível em colunas diferentes;
  7. confere que nenhuma pergunta de categoria aparece em nenhum momento.

- **Rodada real, obrigatória antes de fechar o ticket:**
  ```
  cp ~/.local/share/julius/prices.db /tmp/v23.db
  JULIUS_DB=/tmp/v23.db julius produtos revisar
  ```
  Registrar no corpo deste ticket (ou em `claudedocs/`) três números medidos: quantos produtos entraram na fila (esperado ~86, contra 4 pelo critério antigo), quantas perguntas de conteúdo apareceram (esperado ~6–7) e o custo em US$. **Conferir especificamente que `Ovos Iana 30 unidades` recebe conteúdo** — é a questão 5 em aberto dos requisitos, e é o caso que motivou a funcionalidade de preço por conteúdo.

- **`CLAUDE.md`** — o que precisa mudar de fato:
  - **Status**: fase v2.3, contagem real de testes (medir, não estimar).
  - **Camada opcional de IA**: acrescentar a distinção que organiza tudo — conteúdo **lido de rótulo inequívoco** é automático; conteúdo **inferido por costume de varejo** nunca grava sozinho, só alimenta uma pergunta. Registrar o contraexemplo medido (`Filme PVC 30m x 28cm → 30 UN`, com o modelo se dizendo certo) e a razão: erro de conteúdo não é visível na saída normal, vira um R$/UN plausível — então não passa na condição (2) do teste de duas condições.
  - Registrar que **auto-relato de confiança da IA falhou três vezes** neste projeto (`confidence` na v2; número de tags; "o número veio do rótulo") e que o **único sinal confiável é a recusa** (`null` certo em 6 de 6). É o que impede a próxima sessão de tentar um threshold de novo.
  - **Identidade de produto e busca / Preço por conteúdo**: a pendência agora é por campo faltando, e conteúdo só é cobrado de produto vendido por UN (com a razão: R$/kg já é preço por conteúdo).
  - Registrar o **estreitamento do RF2**: a categoria automática é a primeira **conhecida**, porque o vocabulário de tags é a entrada da medição de `TAG_MATCH_CUTOFF`.
  - **Estrutura de pacote**: prompt `packaging` e `PackagingHint`.
  - **CLI**: `revisar` não pergunta categoria; pergunta conteúdo quando a IA recusa; `--sim` significa "não perguntar nada".
  - **Design de testes**: a regra de que nenhum teste (nem checagem manual) pode apontar `importar` para `tests/fixtures/` já está lá desde o 130 — conferir que continua correta.
  - **Fora de escopo**: acrescentar "gravar conteúdo vindo de intuição sem confirmação" e "score de confiança da IA como gatilho".

- **`README.md`**: o que `revisar` aplica sozinho, o que ele pergunta, e o novo sentido de `--sim`.

- **`index.md`**: estado `feito` nas linhas 131–136.

### Validação
- A contagem de testes no `CLAUDE.md` é o número que `.venv/bin/pytest -q` imprime, não estimativa.
- Nenhuma afirmação sobre a precisão da intuição de varejo além do medido (5 de 7 úteis, 1 erro perigoso, em uma amostra de 9 produtos).

## Especificação técnica

```
modificar tests/test_e2e.py
modificar CLAUDE.md
modificar README.md
modificar docs/tickets/julius-v2/index.md
```

### Padrão a seguir
- O e2e existente usa `CliRunner` com `JULIUS_DB` em `tmp_path` e os helpers `_run`/`_import`/`copied_fixtures`/`restore_fixture` — reaproveite, não crie harness novo.
- O estilo do `CLAUDE.md` é prosa densa com o porquê das decisões e números medidos. Acrescente medição, não adjetivo.

## Testes obrigatórios

1. `test_v23_review_cycle` — os 7 passos acima.
2. `test_v23_kg_product_never_asked_for_content` — regressão isolada do filtro de unidade.
3. Suíte inteira verde, incluindo todos os testes dos tickets 131–135.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; o número final é o que foi escrito no `CLAUDE.md`.
- [ ] `grep -rn NotImplementedError julius` vazio.
- [ ] `git diff --stat julius/` **vazio** neste ticket.
- [ ] A rodada real foi executada contra cópia, e os três números estão registrados.
- [ ] `grep -n "Filme PVC" CLAUDE.md` encontra o contraexemplo registrado.
- [ ] `grep -n "recusa" CLAUDE.md` encontra o registro de que a recusa é o único sinal confiável.
- [ ] Nenhum identificador em português no código novo; nenhuma mensagem de usuário em inglês.

## Rodada real (executada em 2026-09-16, contra cópia do banco de produção)

```
cp ~/.local/share/julius/prices.db <cópia>.db
JULIUS_DB=<cópia>.db julius produtos revisar --sim      # metade automática
JULIUS_DB=<cópia>.db julius produtos revisar            # metade interativa (num pty)
```

Modelo `deepseek-flash`, banco com 105 produtos e 132 preços.

| Número | Medido | Esperado no ticket |
|---|---|---|
| Produtos na fila (`incomplete_product_ids`) | **86** (contra **4** por `untagged_product_ids`) | ~86 contra 4 |
| Perguntas de conteúdo | **5** — Sacola reutilizável, Brócolis Ninja, Filme PVC, Prato descartável, Espátula | ~6–7 |
| Custo | **US$ 0,0095** (4 `enrich` + 1 `merge` + 1 `packaging`) | ~US$ 0,02 |

Aplicado sozinho na passada automática: 1 nome, 5 categorias, 18 conteúdos, 79 tipos.

**Questão 5 dos requisitos, fechada:** `OVOS IANA 30UN MEDIO BCO` recebeu `30 UN` **automaticamente** — o rótulo é inequívoco, então o caso que motivou o preço por conteúdo se conserta sozinho, sem pergunta.

**O contraexemplo apareceu como previsto, e o desenho segurou:** a pergunta do Filme PVC saiu com `[1] 30 UN · unidade` (o modelo lendo "30m x 28cm" como 30 unidades). Nada foi gravado, porque a resposta foi pular. Os candidatos úteis também apareceram: Brócolis `1 UN · unidade`, Prato `10 / 20 / 50 UN · pacote`.

## Notas para o agente
- O ponto mais importante da documentação é **por que a intuição não grava**. Sem isso, alguém daqui a três meses vai achar que faltou automatizar e vai "terminar o trabalho" — e o erro dele só apareceria como um preço por conteúdo errado numa tabela, que é o tipo de erro que este projeto inteiro existe para não cometer.
- Registre também a regra de decisão em uma frase, porque ela generaliza: **a IA pode gravar sozinha o que o usuário consegue ver que está errado.** Nome, categoria e tipo passam; conteúdo inferido não passa.
- Se a rodada real mostrar que `Ovos Iana` **não** recebeu conteúdo, isso não é motivo para mexer no prompt aqui: anote o resultado e pare.

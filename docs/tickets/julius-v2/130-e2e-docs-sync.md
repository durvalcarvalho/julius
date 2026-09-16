# 130: e2e da v2.2 e sincronização de `CLAUDE.md`/`README.md`

> Fecha a fase: um teste ponta a ponta do ciclo novo e os documentos contando a verdade — incluindo a reversão de "conteúdo sempre confirmado", que hoje o `CLAUDE.md` afirma ao contrário.

## Contexto

Mesmo papel do ticket 114 na v2. Fontes: `docs/design/comparability-v2.2.md` e `docs/requirements/comparability-closure.md`.

Depende de **117–129** (é o último da trilha).

## Escopo

### Dentro
- `tests/test_e2e.py`: um teste do ciclo completo da v2.2.
- `CLAUDE.md`: seções "Status", "Camada opcional de IA", "Identidade de produto e busca", "Preço por conteúdo", "Dicas de uso", "CLI", "Estrutura de pacote", "Armazenamento" (migração 0003), "Estrutura do repositório" (entrada/).
- `README.md`: comandos novos e o fluxo de importação.
- `docs/tickets/julius-v2/index.md`: marcar 117–130 como `feito`.

### Fora
- Qualquer mudança de comportamento em `julius/` — este ticket é teste e documentação. Se algo não funcionar, o ticket de origem está incompleto: **pare e anote**, não conserte aqui.
- Reescrever as seções de design antigas do `CLAUDE.md` que usam vocabulário em português: a regra registrada é que o código é a fonte da verdade dos nomes.

## Requisitos

### Funcionais

- **Teste e2e** `test_v22_full_cycle` (ou nome equivalente), usando `ScriptedLlmClient` para a IA:
  1. põe dois fixtures reais na pasta de entrada (`qrcode-3.html` e `qrcode.html`);
  2. roda `julius importar` **sem argumento**;
  3. confere: linhas no banco, produtos com `kind` e `content` aplicados automaticamente, `actions.jsonl` com uma linha por ação, os dois HTML em `entrada/importados/` com nome de data + chave, pasta de entrada limpa;
  4. roda `julius produtos revisar --ultimas-acoes` e confere que a tabela lista as ações com comando de desfazer;
  5. roda `julius consultar tomate` e confere a coluna "Dia" e o destaque;
  6. roda `julius mercados comparar` e confere que o tipo compartilhado aparece com as duas lojas e o rodapé com `n` e período;
  7. desfaz um tipo com `julius produtos tipo ID --remover` e confere que `mercados comparar` deixa de mostrar aquele grupo.

- **`CLAUDE.md`** — o que precisa mudar de fato (não reescrever o documento):
  - **Status**: fase v2.2, contagem real de testes (hoje 394 + os novos; medir, não estimar), migração 0003 aplicada.
  - ⚠️ **"Camada opcional de IA"**: a frase "conteúdo de embalagem **nunca** é gravado sem confirmação explícita, mesmo com `--sim`" está **revertida** pelo ticket 122. Substituir, registrando o motivo (o teste de duas condições de `comparability-closure.md` §4 e os 32 de 79 produtos-UN sem conteúdo que a confirmação produziu) — e mantendo a linha vermelha que **não** mudou: fusão continua manual.
  - **Identidade de produto e busca**: acrescentar o grupo de comparação (`products.kind`) como o mecanismo de comparar entre lojas, e registrar que fusão automática foi **rejeitada por medição** (19 pares acima do corte, pior falso positivo `Alho` ↔ `Pão de Alho` com nota 1,00), não por cautela.
  - **Preço por conteúdo**: acrescentar a regra de base de comparação (KG compara direto; UN exige conteúdo) e que o mínimo/máximo passou a respeitá-la.
  - **Armazenamento**: migração 0003 com o SQL, no formato das outras duas.
  - **Estrutura de pacote**: `domain/comparison_basis.py`, `services/comparison.py`, `infra/receipt_files.py`, `actions.jsonl`.
  - **CLI**: `produtos tipo`, `definir-conteudo --remover`, `revisar --ultimas-acoes`, `mercados comparar`, `importar` sem argumento.
  - **Estrutura do repositório**: o symlink `entrada/` e `entrada/importados/`.
  - **Fora de escopo**: acrescentar fusão automática (rejeitada por medição), índice único de carestia, estatística de dia da semana.

- **`README.md`**: os comandos novos na lista, e o fluxo `make inbox` → Ctrl+S → `julius importar`.

- **`index.md`**: estado `feito` nas linhas 117–130.

### Validação
- A contagem de testes no `CLAUDE.md` precisa ser o número que `.venv/bin/pytest -q` imprime no fim, não uma estimativa.
- Nenhuma afirmação sobre dia da semana além de "a coluna existe": não há dado que sustente padrão semanal.

## Especificação técnica

```
modificar tests/test_e2e.py
modificar CLAUDE.md
modificar README.md
modificar docs/tickets/julius-v2/index.md
```

### Padrão a seguir
- O e2e existente usa `CliRunner` com `JULIUS_DB` em `tmp_path` e helpers `_run`/`_import` — reaproveite, não crie harness novo.
- O estilo do `CLAUDE.md` é prosa densa com o porquê das decisões e com números medidos. Acrescente medição, não adjetivo.

## Testes obrigatórios

1. `test_v22_full_cycle` — os 7 passos acima.
2. `test_import_from_inbox_is_idempotent` — rodar `julius importar` sem argumento duas vezes: a segunda não acha nada (tudo já arquivado) e não duplica linha.
3. Suíte inteira verde, incluindo todos os testes dos tickets 117–129.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde; o número final de testes é o que foi escrito no `CLAUDE.md`.
- [ ] `grep -rn NotImplementedError julius` vazio.
- [ ] `grep -n "nunca é gravado sem confirmação" CLAUDE.md` vazio (a frase revertida saiu).
- [ ] `grep -rn "por que fusão automática" CLAUDE.md` (ou equivalente) encontra o registro da medição, com o par `Alho`/`Pão de Alho` e a nota 1,00.
- [ ] Nenhum identificador em português no código novo; nenhuma mensagem de usuário em inglês.
- [ ] `git diff --stat julius/` vazio neste ticket.

## Notas para o agente
- A reversão do conteúdo confirmado é o ponto mais importante da documentação: alguém lendo o `CLAUDE.md` daqui a três meses precisa entender **por que** a regra mudou, ou vai "restaurar" a confirmação achando que foi regressão.
- Registre também que a fusão automática foi avaliada com dado real e rejeitada. Sem isso, a ideia volta na próxima sessão — ela é intuitiva e a medição que a derruba não é.
- Se qualquer passo do e2e não passar, o ticket de origem ficou incompleto. Anote qual e pare; não implemente comportamento novo aqui.

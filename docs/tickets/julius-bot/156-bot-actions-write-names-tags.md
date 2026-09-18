# 156: `bot/actions.py` — `PendingWrite`, `execute` e as escritas de nome e tag

> Uma ação de escrita não escreve: devolve o que **vai** acontecer, com os nomes lidos do banco. Quem escreve é `execute`, depois do tap.

## Contexto

`docs/design/telegram-bot.md` §4.3 (as duas passadas), §3.3 (validar antes) e §8 (preview computado pelo código, fail-closed). A IA escolhe a ação de escrita e preenche os argumentos; a ação resolve os alvos, monta o preview a partir do banco e devolve uma `PendingWrite` — **nada é gravado**. `execute` é chamado pelo turno do tap (160), em código, sem modelo.

Depende de **154** (render, para as três funções novas dele) e **155** (`Deps`, resolvedores). 157 acrescenta as demais escritas ao mesmo `execute`.

## Escopo

### Dentro
- `julius/bot/actions.py`: `PendingWrite`, `WriteResult`, `WriteFailed`, `execute`, e as ações `rename_product`, `rename_store`, `tag_product`, `untag_product`; `WRITE_ACTIONS` (157 estende).
- `julius/bot/render.py`: `render_pending`, `render_result`, `render_failure`.
- `tests/test_bot_actions_write.py` (157 acrescenta casos aqui).

### Fora
- Tipo, conteúdo, fundir, desfundir (→ 157).
- Nonce/expiração **verificados** e a máquina de estados do chat (→ 160). Aqui a pendência só **nasce** com nonce e instante.
- Botões, Telegram, `actions.jsonl` (o design decidiu: escrita do bot é pedido do usuário, como a CLI, e não entra no log de gravações automáticas).

## Requisitos

### Funcionais

```python
@dataclass(frozen=True)
class PendingWrite:
    action: str                    # nome da ação: "rename_product", "rename_store", "tag_product", "untag_product"
    args: Mapping[str, object]     # já resolvidos/validados: {"product_id": 23, "name": "Tomate"}
    preview: str                   # o que vai acontecer, com nomes lidos do banco — texto simples, sem HTML
    nonce: str                     # secrets.token_urlsafe(8)
    created_at: float              # time.monotonic()

@dataclass(frozen=True)
class WriteResult:
    summary: str                   # o que aconteceu, com o estado anterior
    undo: str                      # o comando da CLI que desfaz

class WriteFailed(Exception):
    """A escrita não aconteceu; str(exc) é o motivo, em português."""

def execute(deps: Deps, pending: PendingWrite) -> WriteResult
```

Ações (mesma forma das de leitura: `async def`, `ctx: RunContext[Deps]`, docstring em português com `Args:`):

| Ação | Parâmetros | Resolve | Preview (texto, sem HTML) | `args` |
|---|---|---|---|---|
| `rename_product` | `product: str, name: str` | `resolve_product` | `Renomear o produto {id} «{atual}» para «{novo}»` | `product_id`, `name` |
| `rename_store` | `store: str, nickname: str` | `resolve_store` | `Dar ao mercado {cnpj} «{atual}» o apelido «{novo}»` | `cnpj`, `nickname` |
| `tag_product` | `product: str, tag: str` | `resolve_product` | `Marcar o produto {id} «{nome}» com a tag «{tag}»` | `product_id`, `tag` (minúsculas) |
| `untag_product` | `product: str, tag: str` | `resolve_product` | `Remover a tag «{tag}» do produto {id} «{nome}»` | `product_id`, `tag` |

- Nome/apelido/tag em branco após `strip()` → `ModelRetry("O nome não pode ficar vazio.")` (ou "A tag…").
- `tag_product` com a tag já presente em `product.tags` → `ModelRetry(f"O produto {id} já tem a tag «{tag}».")`; `untag_product` sem a tag → `ModelRetry(f"O produto {id} não tem a tag «{tag}»; tem: {tags}.")`.
- `nonce = secrets.token_urlsafe(8)`, `created_at = time.monotonic()` — sempre novos.

`execute(deps, pending)`:
- Despacha por `pending.action` (dicionário; ação desconhecida → `WriteFailed("ação desconhecida")`).
- **Lê o estado atual antes de escrever** (nome/apelido/tags de agora, não os do preview — o usuário pode ter mexido pela CLI no intervalo) e monta `undo` a partir dele; depois chama o serviço.
- `catalog.rename_product` / `rename_store` / `tag_product` / `untag_product`; `ValueError`/`LookupError` → `WriteFailed(str(error))`.
- `WriteResult`:
  - rename_product: `summary = f"Produto {id} agora é «{novo}» (antes: «{antes}»)"`, `undo = f'julius produtos renomear {id} "{antes}"'`.
  - rename_store: `summary = f"Mercado {cnpj} agora é «{novo}» (antes: «{antes}»)"`, `undo = f'julius mercados renomear {cnpj} "{antes}"'`.
  - tag_product: `summary = f"Produto {id} «{nome}» marcado com «{tag}»"`, `undo = f"julius produtos tag {id} {tag} --remover"`.
  - untag_product: `summary = f"Tag «{tag}» removida do produto {id} «{nome}»"`, `undo = f"julius produtos tag {id} {tag}"`.
  - Aspas duplas dentro de um nome viram apóstrofo no `undo` (`"` → `'`), para o comando continuar colável.

`render.py`:
- `render_pending(pending: PendingWrite) -> str` → `"⚠️ <b>Confirmar?</b>\n{escape(preview)}"`.
- `render_result(result: WriteResult) -> str` → `"✅ {escape(summary)}\nDesfazer: <code>{escape(undo)}</code>"`.
- `render_failure(reason: str) -> str` → `"❌ Não executado: {escape(reason)}"`.

### Validação e erros
- Uma ação de escrita **nunca** altera o banco: teste lê `canonical_name`/`nickname`/`tags` depois da ação e compara com antes.
- `execute` nunca deixa exceção de `services` escapar sem virar `WriteFailed`; qualquer outra exceção propaga (o turno 160 trata).

## Especificação técnica

```
modificar julius/bot/actions.py      — dataclasses, WriteFailed, execute, 4 ações, WRITE_ACTIONS
modificar julius/bot/render.py       — render_pending, render_result, render_failure
criar     tests/test_bot_actions_write.py
```

### Padrão a seguir
- Mesmo `FunctionModel`/`run_sync` de 155 para chamar a ação pelo agente; `execute` é síncrona — chame direto.
- `cli/products.py::rename_product` e `fundir` são o precedente das mensagens de sucesso e do "desfazer: …" impresso.

## Testes obrigatórios

1. `test_rename_product_returns_pending_and_writes_nothing` — `PendingWrite` com `action == "rename_product"`, `args == {"product_id": id, "name": "Picanha bovina"}`, preview cita o nome atual; `canonical_name` inalterado.
2. `test_execute_rename_product_applies_and_returns_undo` — banco renomeado; `undo == f'julius produtos renomear {id} "{nome antigo}"'`.
3. `test_rename_store_pending_and_execute` — idem para loja, por CNPJ formatado e por apelido.
4. `test_tag_and_untag_pending_and_execute` — marca, `undo` com `--remover`; remove, `undo` sem.
5. `test_tag_already_present_retries` e `test_untag_absent_retries` — `RetryPromptPart` com a mensagem.
6. `test_blank_name_retries` — `{"name": "   "}` → "não pode ficar vazio".
7. `test_execute_reads_current_state_for_undo` — cria a pendência, renomeia pela CLI/serviço no meio, executa: `undo` traz o nome **do meio**, não o do preview.
8. `test_execute_unknown_product_fails_closed` — pendência com `product_id` inexistente → `WriteFailed`, nada gravado.
9. `test_execute_unknown_action_fails` — `action="explode"` → `WriteFailed`.
10. `test_two_pendings_have_distinct_nonces`.
11. `test_render_pending_result_failure_escape` — `&`/`<` escapados; `undo` dentro de `<code>`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n "with conn\|\.execute(\"" julius/bot/actions.py` **vazio** — o bot não fala SQL nem abre transação; isso é de `services`.
- [ ] `grep -n "actions.jsonl\|action_log_path" julius/bot/` **vazio**.

## Notas para o agente

- O preview é o que o usuário vai ler antes de tocar em Confirmar — nomes vêm de `Product`/`Store` lidos do banco pelos ids resolvidos, **nunca** do argumento textual que a IA passou.
- `PendingWrite.args` guarda ids, não nomes: `execute` não pode voltar a resolver por nome (o resultado poderia mudar).
- Não implemente expiração aqui; `created_at` existe para o 160 decidir.

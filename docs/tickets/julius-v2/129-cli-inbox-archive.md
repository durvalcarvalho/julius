# 129: `julius importar` sem argumento, arquivamento automático e o symlink `entrada/`

> Fecha a fricção que abriu a sessão: salvar a nota com Ctrl+S numa pasta fácil de achar e rodar `julius importar`, sem glob, sem caminho decorado e sem limpar nada à mão.

## Contexto

`docs/design/comparability-v2.2.md` §6 (trilha B). `docs/requirements/receipt-inbox.md` RF1–RF5 e as resoluções de `comparability-closure.md` §5.

O pedido original era "uma pasta no repo, porque `~/.local/share/julius/entrada` é fundo demais para achar". A solução escolhida é um **symlink** no repo apontando para a pasta canônica: o Ctrl+S cai em `precos-dos-mercados/entrada/` e o arquivo **já está** no lugar certo — o que dissolve qualquer passo de mover e a pergunta "mover antes ou depois de ler".

Depende de **128** (`Config.inbox_path`/`archive_path`, `receipt_files`, `ImportResult.access_key`).

## Escopo

### Dentro
- `julius/cli/receipts.py`: `files` vira opcional e, vazio, varre a pasta de entrada; arquivamento e descarte do sidecar após cada arquivo importado com sucesso.
- `Makefile`: alvo `inbox`.
- `.gitignore`: `/entrada`.
- `README.md`: o fluxo novo de uso (só a seção de importar).
- Testes: `tests/test_cli_receipts.py`, `tests/test_e2e.py`.

### Fora
- `infra/receipt_files.py` e `Config` (fechados no 128).
- O sinal de extremos e a coluna de dia da semana (→ 127, mesmo arquivo, outro ticket — coordene o diff).
- Watcher/hook que importe sozinho ao aparecer arquivo; comando de limpar a entrada; mover PDF/HAR.
- Acrescentar `/*_files/` ao `.gitignore`: **já existe** (commit `65f2fc7`). Não duplicar.

## Requisitos

### Funcionais

- **Alvo no `Makefile`:**
  ```make
  inbox:
  	mkdir -p ~/.local/share/julius/entrada
  	ln -sfn ~/.local/share/julius/entrada entrada
  ```
  Acrescentar `inbox` ao `.PHONY`. `ln -sfn` é idempotente: rodar duas vezes não empilha link dentro de link.

- **`.gitignore`**: acrescentar `/entrada` (ancorado na raiz, como os outros padrões de dado do usuário). Não mexer nas linhas existentes.

- **`julius importar` sem argumento**: `files` passa a `Annotated[Optional[list[Path]], typer.Argument(...)] = None`.
  - Vazio/`None` → varre `sorted(config.load().inbox_path.glob("*.html"))`. `glob` não é recursivo, então `entrada/importados/` fica invisível — é isso que faz `julius importar` significar "importe o que é novo".
  - Pasta inexistente → mensagem e saída 0: `A pasta de entrada não existe. Crie com: make inbox`
  - Pasta sem `.html` → mensagem e saída 0: `Nada para importar em <caminho>.`
  - Com argumentos, o comportamento é exatamente o de hoje (inclusive glob expandido pelo shell).
  - `--help` do argumento passa a mencionar: "Sem argumento, importa os HTML da pasta de entrada."

- **Arquivamento por arquivo bem-sucedido**, dentro do `try` que já existe por arquivo:
  1. `receipt_files.archive(path, settings.archive_path, purchased_at=result.purchased_at, access_key=result.access_key)`;
  2. `receipt_files.discard_sidecar(path)`.
  A linha de resultado ganha a informação, sem virar duas linhas:
  ```
  qrcode.html: 46 itens novos, 0 já existiam · arquivado como 2026-09-16_5326…9308.html
  ```
  Sidecar removido acrescenta ` (+ qrcode_files/ descartado)`.

- **Arquivo que falha não é movido nem tem sidecar apagado** — as duas chamadas ficam depois do `import_receipt` retornar, dentro do mesmo `try`/`continue` que já trata erro por arquivo. Falha em um arquivo não impede o arquivamento dos outros do mesmo lote.

- Falha no **arquivamento** (não no import): o import já está no banco, então não é erro do comando. Reportar em `stderr` e seguir: `qrcode.html: importado, mas não foi possível arquivar — <motivo>`. Código de saída não muda por causa disso.

### Validação e erros
- Caminho passado explicitamente que não existe → comportamento de hoje (`FileNotFoundError` tratado com a dica `IMPORT_FILE_NOT_FOUND`), inalterado.
- Symlink `entrada` quebrado (aponta para pasta que não existe) → cai no caso "pasta inexistente", com a mesma mensagem.

## Especificação técnica

```
modificar julius/cli/receipts.py     — files opcional, varredura da entrada, archive + discard_sidecar
modificar Makefile                   — alvo inbox
modificar .gitignore                 — /entrada
modificar README.md                  — fluxo de importação
modificar tests/test_cli_receipts.py
modificar tests/test_e2e.py
```

### Padrão a seguir
- `config.load()` dentro do handler (já é feito no mesmo comando para o cliente de IA); nunca em import.
- Mensagens de erro por arquivo em `error_console`, resultados em `console` — a divisão já existente no arquivo.
- Testes de CLI apontam `JULIUS_DB` para `tmp_path`, o que leva `inbox_path`/`archive_path` para lá também — sem precisar de variável nova nem de mock de `Path.home`.

## Testes obrigatórios

1. `test_import_without_args_scans_inbox` — dois HTML na pasta de entrada → os dois são importados, em ordem de nome.
2. `test_import_without_args_missing_inbox_message` — pasta inexistente → mensagem apontando `make inbox`, saída 0, nada gravado.
3. `test_import_without_args_empty_inbox_message` — pasta vazia → mensagem "Nada para importar", saída 0.
4. `test_import_without_args_ignores_archive_subdir` — um HTML já em `entrada/importados/` **não** é reimportado pela varredura.
5. `test_import_archives_on_success` — o arquivo sai da entrada e aparece em `importados/` com o nome de data + chave; a saída menciona o arquivamento.
6. `test_import_discards_sidecar` — `qrcode_files/` ao lado do HTML é removido e a saída diz isso.
7. `test_import_failure_keeps_file_in_place` — HTML inválido → continua na entrada, sem sidecar apagado, com a dica de erro de hoje.
8. `test_import_batch_partial_failure_archives_the_good_ones` — um arquivo válido e um inválido → o válido é arquivado, o inválido fica.
9. `test_import_archive_failure_does_not_fail_command` — `archive_path` impossível (ex.: arquivo no lugar da pasta) → saída em `stderr`, código de saída inalterado, dado no banco.
10. `test_import_with_explicit_paths_still_archives` — passando o caminho na mão, o arquivamento também acontece (não é exclusivo da varredura).
11. `test_e2e_import_from_inbox_end_to_end` — põe um fixture na entrada, roda `julius importar` sem argumento, confere linhas no banco e o arquivo em `importados/`.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `make inbox` cria o link e é idempotente (rodar duas vezes não cria `entrada/entrada`).
- [ ] `git status` não mostra `entrada` como não versionado depois do `make inbox`.
- [ ] Teste manual do ciclo inteiro: Ctrl+S numa página de NFC-e salvando em `entrada/`, `julius importar`, e conferir que a pasta de entrada voltou a ficar limpa e o arquivo está em `entrada/importados/`.

## Notas para o agente
- O symlink é o que substitui toda a lógica de mover que os requisitos originais previam. Não implemente cópia nem movimentação entre repo e `~/.local/share` — se você se pegar escrevendo isso, o desenho foi perdido.
- `glob("*.html")` **não** pode virar `rglob`: é a não-recursividade que faz o arquivado desaparecer da varredura.
- Coordene o diff de `cli/receipts.py` com o 127 (que mexe no mesmo comando, depois da revisão). Os dois pontos de mudança são distintos — arquivamento é por arquivo, sinal é uma vez no fim.
- Não apague o `_files/` antes de arquivar o HTML: a ordem (arquivar, depois descartar) é o que garante que uma falha no meio nunca deixe o usuário sem a fonte.

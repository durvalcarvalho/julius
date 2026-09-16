# 128: `infra/receipt_files.py` — arquivar o HTML importado e descartar o `_files/`

> A infraestrutura de arquivamento: mover a nota para `entrada/importados/` com nome que não colide, e apagar a pasta de peso morto que o Ctrl+S cria junto.

## Contexto

`docs/design/comparability-v2.2.md` §4.9 e §6 (trilha B). `docs/requirements/receipt-inbox.md` RF3–RF5.

Origem do pedido: o usuário salva a página da NFC-e com Ctrl+S e sempre cai `qrcode.html` + `qrcode_files/` na raiz do repo, que ele precisa limpar à mão. A decisão foi **arquivar, nunca apagar** o HTML (o precedente é real: o endereço da loja só foi recuperado em v2 reimportando HTMLs antigos), com uma exceção justificada para o `_files/`, que é jQuery, CSS e um SVG de logo e não pode gerar campo novo nunca.

Independente de todos os tickets de comparabilidade. Pode rodar em paralelo com qualquer um.

## Escopo

### Dentro
- `julius/config.py`: `inbox_path`, `archive_path`.
- `julius/domain/models.py`: `ImportResult.access_key`, `ImportResult.purchased_at`.
- `julius/services/importing.py`: preencher os dois campos novos.
- `julius/infra/receipt_files.py` (novo): `archive`, `discard_sidecar`.
- Testes: `tests/test_config.py`, `tests/test_infra_receipt_files.py` (novo), `tests/test_services_importing.py`.

### Fora
- Chamar essas funções: o `importar` só as usa no 129.
- `Makefile`, `.gitignore`, symlink `entrada` (→ 129).
- Mover PDFs/HARs, comando de limpar a entrada, watcher — fora do escopo desta rodada (`receipt-inbox.md` §7).

## Requisitos

### Funcionais

- `Config.inbox_path -> Path` → `self.db_path.parent / "entrada"`.
- `Config.archive_path -> Path` → `self.inbox_path / "importados"`.
  As duas como `@property`, uma linha cada, no formato de `ai_log_path` (`config.py:27-33`). **Nenhuma variável de ambiente nova** — seguem `JULIUS_DB` de graça, e a decisão registrada é que não existe `JULIUS_ENTRADA`.

- `ImportResult` ganha `access_key: str = ""` e `purchased_at: str = ""` (com default, no fim do dataclass, porque há construção posicional em teste). `importing.import_receipt` preenche os dois a partir do `Receipt` já parseado — dado que ele tem em mãos e hoje descarta.

- `receipt_files.archive(html_path: Path, destination_dir: Path, *, purchased_at: str, access_key: str) -> Path`:
  - nome do destino: `<YYYY-MM-DD>_<access_key>.html`, onde a data são os 10 primeiros caracteres de `purchased_at`.
  - **O rename é obrigatório, não cosmético:** o navegador salva toda nota como `qrcode.html`, então um destino plano colidiria no segundo import. A chave de acesso é a PK da nota, o que torna o nome único e rastreável até o banco.
  - cria `destination_dir` (com pais) se não existir.
  - destino já existente → sobrescreve (mesma chave de acesso significa a mesma nota, logo o mesmo conteúdo).
  - devolve o caminho novo.
  - `purchased_at` vazio ou `access_key` vazio → `ValueError`: arquivar sem nome determinístico é o que causaria colisão silenciosa.

- `receipt_files.discard_sidecar(html_path: Path) -> bool`:
  - deriva o diretório `html_path.parent / f"{html_path.stem}_files"` — ou seja, funciona **a partir do caminho original**, mesmo depois de o HTML já ter sido movido (só usa pai e radical do nome).
  - remove recursivamente **apenas** se existir e for diretório de verdade; devolve `True` se removeu, `False` caso contrário.
  - **nunca** segue symlink: se o caminho for um link, não remove e devolve `False`.
  - nunca lança: falha de permissão vira `False`.

### Validação e erros
- `archive` com `html_path` inexistente → deixa a exceção do sistema de arquivos subir (é erro de programação do chamador; o 129 só chama após import bem-sucedido).
- `discard_sidecar` é a **única** operação destrutiva do sistema: as três guardas (nome exato derivado, precisa ser diretório real, nunca symlink) são requisito, não sugestão.

## Especificação técnica

```
modificar julius/config.py                    — inbox_path, archive_path
modificar julius/domain/models.py             — ImportResult.access_key, .purchased_at
modificar julius/services/importing.py        — preenche os dois campos
criar    julius/infra/receipt_files.py
modificar tests/test_config.py
criar    tests/test_infra_receipt_files.py
modificar tests/test_services_importing.py
```

### Padrão a seguir
- `infra/` pode importar `domain` e `config`, e é onde mora quem fala com o mundo (arquivo, rede) — `infra/ai_log.py` é o vizinho mais próximo em espírito: uma função, sem estado, que não deixa o mundo externo derrubar o programa.
- `shutil.move` para mover (lida com cross-device); remova o destino antes se já existir, para o sobrescrever ser explícito.
- `shutil.rmtree` para o sidecar, com `Path.is_dir()` e `Path.is_symlink()` checados antes.
- Testes em `tmp_path`, com árvores de arquivo de verdade — nenhum mock de filesystem.

## Testes obrigatórios

1. `test_config_inbox_and_archive_paths` — ficam em `<pasta do banco>/entrada` e `<...>/entrada/importados`; seguem `JULIUS_DB`.
2. `test_import_result_carries_access_key_and_purchased_at` — importando um fixture real, os dois campos vêm preenchidos e batem com o cabeçalho da nota.
3. `test_archive_renames_with_date_and_key` — arquivo vai para `2026-09-16_5326...9308.html`.
4. `test_archive_creates_destination_dir` — destino inexistente é criado.
5. `test_archive_overwrites_same_receipt` — arquivar duas vezes a mesma chave não gera segundo arquivo nem erro.
6. `test_archive_two_receipts_named_qrcode_do_not_collide` — **o caso que motiva o rename**: dois arquivos `qrcode.html` de notas diferentes, arquivados em sequência, resultam em dois arquivos distintos no destino.
7. `test_archive_requires_key_and_date` — `access_key=""` e `purchased_at=""` levantam `ValueError`.
8. `test_discard_sidecar_removes_directory` — `qrcode_files/` com arquivos dentro é removido; devolve `True`.
9. `test_discard_sidecar_works_after_html_moved` — HTML já movido para outro lugar; a função ainda encontra e remove o sidecar pelo caminho original.
10. `test_discard_sidecar_absent_returns_false` — sem sidecar → `False`, nada acontece.
11. `test_discard_sidecar_refuses_symlink` — `qrcode_files` como symlink para outra pasta → devolve `False` e **a pasta apontada continua intacta**.
12. `test_discard_sidecar_never_raises` — diretório sem permissão de escrita → `False`, sem exceção.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `tests/test_architecture.py` verde sem edição (`infra` não importa `services` nem `cli`).
- [ ] `grep -rn "receipt_files" julius/cli/` vazio — ninguém chama ainda.
- [ ] O teste do symlink existe e passa: é a guarda que impede a única operação destrutiva do sistema de sair do lugar.

## Notas para o agente
- Não generalize: nada de `archive_any(path)`, nada de mover PDF ou `.har`, nada de padrão configurável de nome. O único formato é data + chave.
- `discard_sidecar` devolve `bool` em vez de lançar porque o chamador (129) usa isso só para informar o usuário — falhar em limpar lixo não pode transformar um import bem-sucedido em erro.
- Se você achar que apagar o `_files/` é arriscado, pare e anote: a exceção ao "nunca apagar" está justificada no design §6 e pendente de veto do usuário, mas a função pode existir sem ser chamada.

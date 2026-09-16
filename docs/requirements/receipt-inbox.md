# Julius — pasta de entrada de recibos (inbox) + arquivamento: requisitos

> **Q1–Q5 fechadas em `docs/requirements/comparability-closure.md` §5** (mesmo dia). Em resumo: a pasta de queda vira um **symlink `entrada/` na raiz do repo** apontando para `~/.local/share/julius/entrada/` — o que dissolve RF2 (não há mais passo de mover, só um local físico) e Q2; `julius importar` sem argumento varre `entrada/*.html`; o arquivo arquivado é renomeado com data + chave de acesso (o navegador salva tudo como `qrcode.html` e colidiria); `_files/` é a única exceção proposta a "nunca apagar".

> Brainstorm de 2026-09-16 (`/sc:brainstorm`), disparado por um uso real: `julius importar` rodado contra `/home/durval/precos-dos-mercados/qrcode.html` (compra nova, FL 3 Costa, 46 itens) — o Ctrl+S da nota caiu, como sempre, na raiz do repo (`qrcode.html` + `qrcode_files/`), e o usuário perguntou onde deveria salvar isso.
> Insumos: resposta do usuário ao brainstorm; `CLAUDE.md` (seção "Estrutura do repositório", convenção já registrada de `~/.local/share/julius/entrada/`); `.gitignore` atual; código real de `julius/services/importing.py` e `julius/cli/receipts.py::import_receipts`.
> Próximo passo: `/sc:design` → tickets em `docs/tickets/julius-v2/` (117+).

## 0. Ponto de partida — fatos verificados

| # | Fato | Evidência |
|---|---|---|
| F1 | `julius importar` recebe uma lista de `Path` (glob resolvido pelo shell) e nunca toca o sistema de arquivos além de ler o conteúdo — sem mover, arquivar ou apagar nada. | `services/importing.py::import_receipt` só chama `path.read_text(...)`; `cli/receipts.py::import_receipts` só itera e chama essa função. |
| F2 | A convenção "salve em `~/.local/share/julius/entrada/`" já está documentada, mas não é imposta por nenhum código — é só prosa no `CLAUDE.md`. Não existe `Config.entrada_path` nem qualquer lógica que leia esse diretório automaticamente. | `julius/config.py` tem `db_path`, `ai_log_path`, `query_log_path` — nenhuma propriedade de "entrada". |
| F3 | O `.gitignore` atual ancora `/*.html`, `/*.pdf`, `/*.har` na raiz do repo pra não versionar um Ctrl+S solto — mas **não tem nenhum padrão pra diretórios** tipo `qrcode_files/`. Confirmado agora: `qrcode_files/` está solto na raiz, sem ser ignorado. | `cat .gitignore`; `git status` mostra `?? qrcode_files/` no início desta conversa. |
| F4 | Notas antigas do mesmo tipo (`qrcode-4.html`, `qrcode-5.html`, PDFs, `.har`, pastas `*_files/`) já foram movidas manualmente uma vez para `~/.local/share/julius/entrada/` (registrado em "Status da limpeza dos arquivos atuais" no `CLAUDE.md`) — ou seja, o usuário já fez esse trabalho à mão antes; o pedido agora é não repetir isso pra sempre. | `CLAUDE.md`, seção "Status da limpeza". |
| F5 | O caminho de entrada é o único ponto do sistema que já lê arquivo por arquivo e decide sucesso/falha por arquivo (`for path in files: try: importing.import_receipt(...) except ...`) — um bom lugar natural pra um passo de pós-processamento por arquivo, sem tocar nos outros arquivos do lote. | `cli/receipts.py::import_receipts`. |

## 1. Objetivo

Tirar do usuário a tarefa manual de "achar a pasta certa" (hoje: `~/.local/share/julius/entrada/`, um caminho fundo o suficiente pra ser inconveniente de navegar) sem reabrir a decisão de que dado de usuário nunca é versionado no repo. Um diretório dentro do próprio repo — gitignorado — serve só como zona de queda (Ctrl+S cai aí, fácil de achar no explorador de arquivos/editor); `julius importar` se encarrega de levar o conteúdo pro lugar canônico (`entrada/`) e, depois de um import bem-sucedido, arquivar a fonte em vez de deixá-la solta ou apagá-la.

## 2. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | Existe um diretório dentro do repo (gitignorado) que serve como zona de queda — nome e caminho exatos são questão de design (§6 Q1), não desta lista. |
| RF2 | Rodar o import relaciona esse diretório de queda com `~/.local/share/julius/entrada/`: o conteúdo lá pousado termina, em algum momento do fluxo, dentro de `entrada/`. A ordem exata (mover antes de ler vs. ler de onde está e mover depois de escrever) é questão de design (§6 Q2) — o usuário não tem preferência forte, só quer que aconteça sem intervenção manual. |
| RF3 | Depois que um arquivo é importado **com sucesso**, a fonte (o `.html` e, quando presente, a pasta `_files/` que vem junto do Ctrl+S) é **arquivada, nunca apagada** — decisão explícita do usuário nesta sessão. |
| RF4 | Um import que **falha** (erro de parse, unidade desconhecida, arquivo não encontrado) não move nem arquiva nada — a fonte continua exatamente onde estava, pronta pra o usuário corrigir e tentar de novo. Isso é a mesma garantia que `import_receipt` já dá pro banco ("nada parcial"), estendida ao arquivo de origem. |
| RF5 | Falha em um arquivo do lote não deve impedir o arquivamento dos outros arquivos do mesmo lote que tiveram sucesso — mesma independência por arquivo que `import_receipts` já tem hoje (F5). |

## 3. Requisitos não funcionais

- **N1** Diretório de queda gitignorado — nenhum HTML/`_files/` de compra real pode ser versionado por acidente (mesma motivação que already levou aos padrões `/*.html`/`/*.pdf`/`/*.har` no `.gitignore`).
- **N2** Zero dependência nova — mover/arquivar arquivo é `shutil`/`pathlib`, stdlib.
- **N3** Não pode interferir com `tests/fixtures/*.html`, que continuam versionados normalmente.
- **N4** Corrige de forma independente o gap já encontrado em F3 (`qrcode_files/`-like sem padrão no `.gitignore`) — vale mesmo que a feature de mover/arquivar não saia neste ciclo, porque hoje um `git add -A` desavisado versionaria lixo binário (jQuery, CSS, SVG) sem nenhum valor.

## 4. Decisões do usuário (Q&A do brainstorm)

| Questão | Decisão |
|---|---|
| Onde o Ctrl+S deveria cair? | **Um diretório dentro do repo**, pra não precisar navegar até um caminho fundo em `~/.local/share/`. |
| E o dado real do usuário, que a decisão original marcava como "nunca no repo"? | Resolvido pela automação: o diretório do repo é só zona de queda temporária — `julius importar` já leva o conteúdo pra `entrada/` (mover-e-ler ou ler-e-mover, sem preferência do usuário entre as duas ordens). |
| O que fazer com a fonte depois de importar com sucesso? | **Arquivar, nunca apagar** — justificado por precedente real: o backfill do endereço da loja (v2) só foi possível reimportando HTMLs antigos; apagar teria bloqueado isso. |

## 5. Histórias de usuário

- Como usuário, salvo a nota (Ctrl+S) numa pasta fácil de achar dentro do próprio repo, sem decorar nem navegar até `~/.local/share/julius/entrada/`.
- Como usuário, depois de rodar `julius importar`, a nota processada não fica mais solta nem no repo nem numa pasta de queda — ela vai pra um lugar arquivado, e eu sei que nunca é apagada, então nunca perco a fonte se algum dado novo precisar ser extraído dela no futuro.
- Como usuário, se o import falhar (unidade desconhecida, arquivo corrompido), a nota continua exatamente onde eu a deixei — não preciso procurar em outro lugar pra corrigir e tentar de novo.

## 6. Questões em aberto (para `/sc:design`)

| # | Questão | Observação |
|---|---|---|
| Q1 | Nome e caminho exato do diretório de queda dentro do repo (ex.: `inbox/`, `recibos/`). | Só precisa ser raso e fácil de achar — é o requisito real (F do brainstorm), não o nome em si. |
| Q2 | Ordem mover-depois-ler vs. ler-depois-mover. | Mover antes simplifica ("só existe um lugar pra ler, `entrada/`") mas complica RF4 (onde fica a fonte de um import que falha, se já foi movida?); ler-depois-mover resolve RF4 de graça (fonte só sai do lugar depois de confirmado sucesso), mas mantém dois locais possíveis de leitura. Medir contra RF3/RF4 antes de decidir. |
| Q3 | `julius importar` sem nenhum argumento deveria escanear o diretório de queda/`entrada/` automaticamente, fechando de vez o "tenho que procurar o caminho"? Ou continua exigindo o glob explícito, só que agora mais curto (`julius importar inbox/*.html`)? | Não decidido pelo usuário nesta rodada — impacta a assinatura da CLI (`files: list[Path]` hoje é obrigatório). |
| Q4 | Onde arquivar dentro de `entrada/` — uma subpasta única (`entrada/importados/`) ou uma por data/mês? | Sem preferência expressa; subpasta única é o suficiente pro volume atual (algumas notas por mês). |
| Q5 | `_files/` (jQuery/CSS/SVG do Ctrl+S) — arquivar junto com o `.html` ou descartar só esse (nunca é lido pelo parser, sem valor histórico), mantendo "nunca apagar" restrito ao `.html`? | O usuário disse "arquivar, nunca apagar" de forma geral, sem diferenciar `_files/`; vale confirmar no design se a exceção (descartar só o `_files/`) é aceitável, já que é peso morto (ver `CLAUDE.md`, "Fixture leva só o `.html`"). |

## 7. Fora do escopo desta rodada

Mover PDFs/HARs (já resolvido manualmente uma vez, sem pedido de automatizar); comando dedicado de "limpar `entrada/`"; qualquer watch/hook que dispare o import automaticamente quando um arquivo aparece na zona de queda (não foi pedido, seria automação além do que a fricção relatada justifica).

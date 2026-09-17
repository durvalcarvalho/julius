# Julius — apelido de mercado que já nasce reconhecível: requisitos

> Brainstorm de 2026-09-17 (`/sc:brainstorm`), disparado por uso real: o usuário rodou `julius mercados renomear` **duas vezes seguidas** para separar duas filiais da Dona de Casa (`11832478000285` → "DONA DE CASA Guará", `11832478000366` → "DONA DE CASA CANDANGOLANDIA") e perguntou se não daria para descobrir a cidade pelo CNPJ via API pública, com "2 ou 3 APIs em paralelo, usando a primeira que responder" como fallback.
> Insumos: banco real (`~/.local/share/julius/prices.db`, 5 lojas), os 6 HTMLs reais de `~/.local/share/julius/entrada/`, `julius/parsers/df.py`, `julius/repositories/stores.py`, `julius/cli/stores.py`, `julius/services/guidance.py`.
>
> **Segunda rodada, mesmo dia (`/sc:research`)**, disparada pela resposta dele à §6: *"esses nomes de razão social aí é uma merda, o que o usuário sabe mesmo é o nome fantasia, e o lugar onde ele foi; depois quando ele tiver consultando, se retornar um nome estranho ele nem vai saber onde é."* Isso responde Q3 ("resolver") e move o trabalho B (§1) de questão aberta para requisito. As medições da pesquisa estão em §7; Q3 foi reescrita como achado.
> **Implementado em 17/09/2026** (`/sc:implement`): §8 registra o que foi construído e a rodada real.

## 0. Ponto de partida — fatos medidos

Nada aqui é estimativa: os números vêm do banco de produção, dos 6 recibos reais e de chamadas reais às APIs públicas.

**O fato que resume o pedido está no banco dele.** `COMERCIAL DE ALIMENTOS HTP LTDA` é a única loja que ele **nunca renomeou** — e o nome fantasia dela é `SUPERMERCADO VENEZA` (F8). É a frase dele acontecendo: um nome estranho na tabela, e ele não tem como saber onde é. Não é preguiça de digitar `renomear`; é que a razão social não permite identificar a loja para poder renomeá-la. Todo o resto deste documento é secundário a essa linha.

| # | Fato | Evidência |
|---|---|---|
| F1 | O endereço da loja **já é extraído** pelo parser e gravado em `stores.address`. Rodado contra os 6 HTMLs reais: **6 de 6** devolveram endereço completo, nenhum `None`. | `DFReceiptParser.parse` em cada arquivo de `entrada/`: `_ADDRESS` casou em todos. |
| F2 | O endereço do cupom traz **bairro, cidade e UF**. O bairro é o segmento **antepenúltimo** separado por vírgula (`[-3]`), e essa posição vale **5 de 5** endereços distintos: `GUARA II`, `GUARA II`, `CANDANGOLANDIA`, `St Complementares`, `AGUAS CLARAS`. | Split por `,` nos 5 endereços gravados/parseados. |
| F3 | **Medido:** o segmento de cidade é `BRASILIA` em 5 de 5 lojas — constante, não distingue nada. **Inferido (nenhuma API foi chamada):** Brasília é um município único e a região administrativa aparece como bairro, então o campo "município" de uma API de CNPJ carrega essa mesma constante e **não separaria as duas filiais da Dona de Casa** que motivaram o pedido. Bairro separa; cidade não. | Segmento `[-2]` dos 5 endereços: `BRASILIA`, `BRASILIA`, `BRASILIA`, `Brasilia`, `BRASILIA`. A parte inferida é raciocínio sobre a divisão administrativa do DF, não medição. |
| F4 | Duas das 5 lojas têm `address IS NULL` no banco (`11832478000285` e `20209736000181`) — **não é falha de extração**: são lojas cujo recibo foi importado antes da migração 0002, que criou a coluna. O HTML das duas está em `entrada/` e parseia o endereço certo hoje (F1). | `SELECT cnpj, address FROM stores`; `ensure_store` usa `COALESCE(excluded.address, stores.address)`, então reimportar preenche. O `CLAUDE.md` já agenda esse backfill ("Próximo passo sugerido: rodar `julius importar`"). |
| F5 | O apelido **nunca** é sobrescrito por import: `ensure_store` tem `ON CONFLICT(cnpj) DO UPDATE SET address = ...` e não menciona `nickname`. Logo, reimportar sozinho **não** aplica apelido melhor nenhum — mesmo depois do backfill de endereço, as 5 lojas continuam com o apelido que têm hoje. | `julius/repositories/stores.py::ensure_store`. |
| F6 | O sistema já sabe detectar filiais da mesma rede e já usa `nickname == legal_name` como "o usuário ainda não nomeou isto". | `guidance.py`: `SAME_CHAIN_BRANCHES` (agrupa por `cnpj[:8]`) e `FIRST_IMPORT_NAME_STORES`. |
| F7 | O bairro **não** identifica loja unicamente: `COMERCIAL DE ALIMENTOS HTP` (`20209736000181`) e `DONA DE CASA` (`11832478000285`) estão as duas em `GUARA II`. Ele distingue **filiais de uma mesma rede**, que é o caso do pedido. | F2, comparando as duas linhas `GUARA II`. |
| F8 | `COMERCIAL DE ALIMENTOS HTP LTDA` = **`SUPERMERCADO VENEZA`**, e é a única loja do banco que ele nunca renomeou. A razão social não contém nenhuma pista do nome real. | `SELECT nickname FROM stores` (= `legal_name`) + consulta real de CNPJ (§7). |
| F9 | O nome fantasia **não existe em nenhuma fonte local**. No HTML: `grep` por `assa[íi]`, `atacad`, `fantasia`, `super`, `hiper` nos 6 recibos → 0 ocorrências (só "DONA DE CASA", que já é a razão social). No PDF de `entrada/`: um único objeto de imagem (`/Im0 Do`), zero texto — exigiria OCR, que o `CLAUDE.md` já põe fora de escopo. | `grep` nos 6 HTMLs; descompressão dos streams do PDF (1 stream, só o operador de imagem). |

## 1. O apelido faz dois trabalhos diferentes — e a medição só fecha um

O usuário editou três apelidos até hoje. Eles não são o mesmo problema:

| Trabalho | Exemplo real dele | A fonte existe no cupom? |
|---|---|---|
| **A — sufixo de lugar**, para separar filiais da mesma rede | `DONA DE CASA S/A` → `DONA DE CASA Guará` e `DONA DE CASA CANDANGOLANDIA` | **Sim.** `stores.address`, já parseado, bairro em `[-3]`, 5/5 (F1, F2). |
| **B — nome que a pessoa reconhece**, quando a razão social não lembra nada | `SENDAS DISTRIBUIDORA S/A` → `ASSAI-ATACADISTA`; e o caso que ele **não** conseguiu resolver, `COMERCIAL DE ALIMENTOS HTP LTDA` = `SUPERMERCADO VENEZA` (F8) | **Não, em nenhuma fonte local** (F9): nem no HTML, nem no PDF (imagem). Registro de CNPJ cobre 2 de 5 (§7.1). |

**F3 encerra a API de CNPJ para o trabalho A**: o campo que ela oferece (município) é constante `BRASILIA` nas 5 lojas e não separaria as duas Dona de Casa. Chamar 3 APIs em paralelo para obter um dado que já está no banco, offline, sem rate limit e sem mock de rede nos testes, é rede a mais para informação a menos.

**F3 não encerra o trabalho B.** Aí a razão social realmente não basta e o cupom não tem o dado — uma consulta externa é uma fonte plausível, e `mercados renomear` já é o desfazer. Os dois trabalhos precisam de decisões separadas (§6).

## 2. Objetivo

Fazer o apelido de um mercado novo **já nascer** distinguível, para que o usuário não precise rodar `mercados renomear` uma vez por filial — sem inventar nome que ele não reconheça e sem tirar dele a palavra final (`renomear` continua sendo a verdade).

## 3. Requisitos funcionais

| # | Requisito |
|---|---|
| RF1 | Um mercado cujo apelido o usuário ainda não editou deve receber um apelido que inclua o **bairro** do endereço do cupom, para que duas filiais da mesma rede nunca apareçam com o mesmo texto. *(O predicado nasceu como `nickname == legal_name`, o mesmo de `FIRST_IMPORT_NAME_STORES` — F6; a implementação o ampliou para `domain.normalization.is_unnamed`, ver Q2.)* |
| RF2 | Um apelido **editado pelo usuário** nunca é sobrescrito, em nenhuma hipótese — nem por import, nem por sugestão automática. É a garantia que `ensure_store` já dá hoje (F5) e que não pode regredir. |
| RF3 | O sufixo de lugar vem de `stores.address`, já no banco — **sem chamada de rede** para esse fim (F1, F2, F3). |
| RF4 | Quando não há nada a compor — sem nome fantasia **e** sem bairro extraível (endereço `NULL`, loja anterior à migração 0002, F4) — o apelido continua sendo a razão social. Nada de placeholder inventado. |
| RF4b | A dica de renomear continua convidando enquanto o apelido não vier de uma pessoa: um apelido composto **só com o bairro** carrega a razão social do cupom, então é tão irreconhecível quanto antes e segue pendente (implementado em `is_unnamed`, ver Q2). |
| RF5 | O `renomear` manual continua existindo e funcionando igual, como correção e como desfazer. |
| RF6 | O apelido de um mercado que o usuário ainda não editou deve trazer o **nome fantasia** quando ele existir, porque é o nome pelo qual ele reconhece a loja — e é o que resolve o caso `HTP` → `Supermercado Veneza`, que ele hoje não consegue nem identificar para renomear (F8). |
| RF7 | Nome fantasia **desconhecido não é erro**: quando nenhuma fonte souber, a loja continua com a razão social e volta a aparecer na dica de renomear que já existe. Nunca inventar nome nem deixar campo em branco na tela. |
| RF9 | As duas fontes de nome fantasia — registro de CNPJ e IA — cobrem conjuntos praticamente disjuntos (F18): usar só uma delas deixa loja descoberta que a outra resolveria. Qual roda primeiro e o que é gravado sem perguntar é Q5. |
| RF10 | A **recusa** da IA tem de ser preservada como sinal: nome fantasia é gravado só quando a fonte afirma, nunca por palpite, e nunca derivado de reformatar a razão social (F16 — `DONA DE CASA S/A` → `Dona de Casa` é indistinguível de reformatação, e um mecanismo que aceita isso aceitaria qualquer coisa). Mexer no texto do prompt invalida a medição de F15, mesma disciplina já registrada para o prompt `packaging`. |
| RF8 | O nome que `julius consultar` mostra é o mesmo apelido — é lá que a reclamação dele aparece ("quando ele tiver consultando"). Nenhum mecanismo novo de exibição: corrigir o apelido corrige `consultar`, `mercados listar` e `mercados comparar` de uma vez. |

## 4. Requisitos não-funcionais

| # | Requisito |
|---|---|
| RNF1 | Zero dependência nova e zero chamada de rede para o trabalho A. `str.split(",")` sobre um campo que já está no banco. |
| RNF2 | A leitura de posição do segmento é **ancorada à direita** (`[-3]`) de propósito: vírgula dentro do nome da rua desloca índice contado da esquerda, e segmento vazio no meio (`, , `) não atrapalha o `[-3]`. Medido 5/5 (F2). |
| RNF3 | O layout do endereço é uma premissa do **template do DF**, não uma verdade universal de NFC-e. Fica isolada junto do que já é específico de estado, pela mesma disciplina do parser — relevante para a nota de "outros estados" da v3. |
| RNF5 | **O lugar continua vindo do cupom, não da API** — mesmo que a consulta de CNPJ devolva bairro na mesma resposta. Medido: o cupom é melhor em 2 de 5 (`AGUAS CLARAS` contra `AREA DE DESENVOLVIMENTO ECONOMICO (AGUAS CLARAS)`), a API é melhor em 1 (`SETORES COMPLEMENTARES` contra `St Complementares`) e as duas **discordam** em 1 (cupom `GUARA II`, API `GUARA`). Nenhum dos dois ganha no geral, e o cupom não precisa de rede. Registrado para o design não adotar a API como fonte de lugar só porque o campo veio junto. |
| RNF4 | Nenhum dado gravado automaticamente sem o par "visível na tela + comando de desfazer" (regra já vigente do projeto). Apelido passa: aparece em `mercados listar`, `consultar` e `mercados comparar`, e `renomear` desfaz. |

## 5. Teto conhecido (aceito, não é bug)

Duas filiais da mesma rede **no mesmo bairro** continuariam com apelidos iguais. Não existe esse caso nos dados (F7 mostra bairro repetido entre redes *diferentes*, não dentro da mesma), e `cli/stores.py::_labels` já resolve colisão de apelido anexando o CNPJ na tabela de comparação. Não vale código novo agora.

Interação a não descobrir no design: `_labels` só dispara quando dois apelidos colidem. Se Q1 sair "derivado", os apelidos param de colidir e `_labels` simplesmente deixa de atuar — inofensivo. Se sair "gravado" **e** Q2 for "só mercado novo", o catálogo fica misto (loja nova com bairro, loja antiga sem) e `_labels` continua disparando no par antigo.

## 6. Questões — todas decididas (implementado em 17/09/2026)

**Q1 — o sufixo é gravado ou derivado na exibição? → DECIDIDA: gravado, por uma restrição que o brainstorm não tinha.** O brainstorm concluiu "pende pra derivado" olhando só para o lugar, que é local. Mas o nome fantasia custa uma chamada de rede, e derivar na leitura significaria consultar o registro a cada `consultar` — o que quebra frontalmente a regra de frequência em que o orçamento de IA se apoia. Partir o apelido em duas metades (lugar derivado, fantasia gravado) é pior que uma só. Então o apelido é composto uma vez e gravado, e `mercados renomear` é o desfazer.

**Q2 — retroatividade → DECIDIDA: sim, e sem passada especial.** A objeção da F5 (`ensure_store` nunca toca `nickname`, então gravar só dispararia na criação) foi resolvida pelo predicado, não por um comando de migração: `domain.normalization.is_unnamed` considera pendente tanto `nickname == legal_name` quanto um apelido que este código compôs **só com o lugar**. Um apelido assim é provisório — carrega a razão social do cupom, é tão irreconhecível quanto antes, e tratá-lo como pronto faria um registro momentaneamente fora do ar custar o nome fantasia para sempre. Apelido digitado à mão não casa com nenhuma das duas formas e nunca é candidato.

**Q3 — o trabalho B (nome fantasia) fica para quando? → RESPONDIDA: agora.** Ele reafirmou que é o problema principal ("o que o usuário sabe mesmo é o nome fantasia"). Virou RF6/RF7 e a pesquisa está em §7. O que sobrou de decisão está na Q4.

**Q4 — o buraco do Assaí: vale a terceira fonte? → MEDIDA (§7.4/§7.5), e a pergunta mudou de forma.** A IA acertou `Assaí Atacadista` e recusou os dois controles fabricados (F14, F15), então ela não é um "fallback para quando a API falha" — é uma **fonte complementar de primeira classe**: registro cobre 4/5, IA cobre 2/5, e a união cobre **5/5**, com acertos em conjuntos praticamente disjuntos (F18, F19). O que resta decidir não é *se* usar as duas, e sim:

**Q5 — as duas fontes, em que ordem e com que gravação? → DECIDIDA e implementada.**
- **Ordem:** registro primeiro, IA só para o que ele deixar vazio (F20).
- **Onde cada uma roda:** `importar` faz **só** o registro (grátis); a IA roda em `mercados revisar`. Motivo medido, não estético: um mercado que nenhuma fonte conhece continua pendente de propósito (Q2), então uma chamada de IA no `importar` se repetiria a cada import — e a suíte já cobrava a invariante "reimportar não chama IA". A fonte paga roda onde o usuário pede.
- **Gravação:** automática, sem perguntar. O apelido passa no teste de duas condições (aparece em `mercados listar`, `consultar` e `mercados comparar`; `mercados renomear` desfaz), e a v2.2 já mediu que a confirmação obrigatória vira fricção que derruba a funcionalidade. Cada gravação vira uma linha em `actions.jsonl` com o comando de desfazer.
- **Discordância entre as fontes:** não pode acontecer no desenho escolhido — a IA só é consultada sobre o que o registro não respondeu.
- **A tensão RF10 × F16 foi resolvida pela ordem, não por um detector.** `DONA DE CASA S/A` → `Dona de Casa` é indistinguível de reformatação, mas o registro cobre essa loja, então a resposta da IA nunca é usada ali. **Não foi implementado** nenhum detector de "isto é só a razão social reformatada": seria uma heurística nova sem medição (e um valor correto a menos), e o erro que ela evitaria é um apelido levemente arrumado, visível e reversível. A proibição continua valendo onde foi medida: no texto do prompt.

## 7. Pesquisa (`/sc:research`) — chamadas reais, 5 CNPJs reais

### 7.1 O que o registro de CNPJ entrega, loja por loja

Quatro provedores públicos consultados sem chave: BrasilAPI, ReceitaWS, CNPJá Open, `publica.cnpj.ws`, `minhareceita.org`.

| CNPJ | Razão social (o que ele vê hoje) | `nome_fantasia` | Veredito |
|---|---|---|---|
| `20209736000181` | COMERCIAL DE ALIMENTOS HTP LTDA | **SUPERMERCADO VENEZA** | **Ganho grande** — nome sem nenhuma relação com a razão social; é a loja que ele nunca renomeou (F8) |
| `27289076001379` | FL 3 COSTA MULTICANAL S A | **COSTA ATACADAO** | **Ganho** — confere com o "FL 3 COSTA ATACADAO" que o `CLAUDE.md` registrou como visível só no PDF |
| `11832478000285` | DONA DE CASA S/A | DONA DE CASA | Redundante — já dava para reconhecer |
| `11832478000366` | DONA DE CASA S/A | DONA DE CASA | Redundante |
| `06057223052643` | SENDAS DISTRIBUIDORA S/A | **vazio** | **Falha, e no pior caso** — é o Assaí, o que ele renomeou à mão |

| # | Fato | Evidência |
|---|---|---|
| F10 | **2 de 5 lojas ganham informação real** com a consulta, **2 de 5 são redundantes** e **1 de 5 falha**. A distribuição importa mais que a taxa: os casos são qualitativamente diferentes, não amostras de um percentual. | Tabela acima. |
| F11 | O nome fantasia do Assaí **não está em nenhum dos 4 provedores** — todos devolvem vazio para `06057223052643` (`''`, `''`, `None`, `None`). "ASSAÍ" é marca comercial do grupo Sendas, e o campo do registro é declaratório e opcional; nada obriga a filial a preenchê-lo. | Chamada aos 4; `WebSearch` confirma o caráter opcional/declaratório do campo. |
| F12 | **Os 4 provedores são, na prática, uma fonte só.** Para os dois CNPJs testados nos quatro, os valores batem exatamente — incluindo a ausência idêntica; BrasilAPI e `minhareceita.org` devolveram até a mesma ordem de chaves no JSON. *Inferido* (não li a documentação deles): todos derivam do dump aberto de CNPJ da Receita Federal. | Comparação campo a campo de `06057223052643` e `20209736000181` nos 4. |
| F13 | CNPJá devolve o fantasia em caixa de título (`Supermercado Veneza`); os outros em maiúsculas (`SUPERMERCADO VENEZA`). Só um deles já sai legível numa tabela. | Campo `alias` vs. `nome_fantasia`/`fantasia`. |

### 7.2 A ideia das "2 ou 3 APIs em paralelo" — o que ela compra de verdade

Ela compra **disponibilidade, não cobertura** (F12): se o campo está vazio na origem, está vazio nos quatro. E aí entra o argumento que dispensa a máquina toda: a consulta acontece quando aparece **loja nova** — 5 em vários meses de uso. Para uma busca que pode simplesmente tentar de novo no mês seguinte, redundância contra indisponibilidade é engenharia para um problema que não chega a existir. Uma API, e se ela falhar a loja fica com a razão social e volta a aparecer na dica que já existe (`FIRST_IMPORT_NAME_STORES`, F6) — que é exatamente o comportamento de hoje, sem regressão.

### 7.3 Fontes descartadas por medição

| Fonte | Por que não |
|---|---|
| HTML do cupom | 0 ocorrências de nome fantasia nos 6 recibos (F9) |
| PDF do cupom | imagem única, sem texto; exigiria OCR, fora de escopo (F9) |
| OpenStreetMap / Nominatim | o endereço do cupom (`SMAS Trecho 3`) resolve para a **via** (`highway`, `SMAS Trecho 03`), não para o estabelecimento. E buscar "Assaí Atacadista" acha POIs em Niterói, São Bernardo e Manaus — só funciona se você já souber a marca, que é a pergunta. Circular. |
| Google Places | teria o nome popular, mas exige chave e cartão — desproporcional para 5 consultas em meses, e o projeto não tem nenhuma credencial paga hoje além da IA. Não testado. |

### 7.4 A medição da IA — feita (`deepseek-flash`, 3 rodadas, a pedido dele)

Ele autorizou rodar; as `JULIUS_AI_*` estavam acessíveis via `~/.bashrc`. Chamada única em lote pelo `HttpLlmClient` real (com `thinking` desligado), 6 lojas, **4 reais + 2 razões sociais fabricadas como controle** — porque a regra medida do projeto é que o único sinal confiável da IA é a recusa, e um nome inventado para uma empresa inexistente seria, em produção, indistinguível de um acerto. Script em `scratchpad/smoke_fantasia.py`.

| # | Razão social | IA devolveu | |
|---|---|---|---|
| 1 | SENDAS DISTRIBUIDORA S/A | **`Assaí Atacadista`** (+ `chain: "Sendas"`) | **acerto — é a pergunta original** |
| 2 | COMERCIAL DE ALIMENTOS HTP LTDA | `null` | recusou (a API sabia: Veneza) |
| 3 | COSTA MULTICANAL S/A | `null` | recusou (a API sabia: Costa Atacadão) |
| 4 | DONA DE CASA S/A | `Dona de Casa` | correto, mas **não conta como conhecimento** (ver F16) |
| 5 | MERCANTIL TREVISAN VALDIVINO LTDA *(falsa)* | `null` | **recusou corretamente** |
| 6 | COMERCIAL DE ALIMENTOS ZURIQUE BRASIL LTDA *(falsa)* | `null` | **recusou corretamente** |

| # | Fato | Evidência |
|---|---|---|
| F14 | **A resposta à pergunta é sim:** o modelo devolve `Assaí Atacadista` para `SENDAS DISTRIBUIDORA S/A` — texto que **não aparece em nenhum lugar da entrada**, o que é o que sustenta a afirmação de conhecimento. (O campo `chain: "Sendas"` que veio junto **não** sustenta nada: `Sendas` é substring literal da razão social de entrada, o único valor daquela linha que casamento de texto produziria.) | Rodadas 1–3, saída idêntica. |
| F15 | **A recusa se sustentou: 2 controles fabricados, 2 recusas, zero invenção** — inclusive no controle 6, desenhado para imitar o padrão do acerto da API (`COMERCIAL DE ALIMENTOS <marca> LTDA`, igual ao HTP/Veneza). Quarta confirmação da regra do projeto, e a primeira fora do domínio de conteúdo de embalagem. **A evidência são os 2 controles, não as 3 rodadas**: com `temperature = 0` e prompt idêntico, repetir só descarta não-determinismo — não amplia a amostra. | `null` nos dois controles, nas 3 rodadas. |
| F16 | `Dona de Casa` é a razão social menos o `S/A`. O prompt proibia explicitamente derivar o fantasia reformatando a razão social, mas **não há como distinguir** conhecimento de reformatação nesse caso. Está correto (a API confirma), mas não é evidência de nada — a contagem honesta da IA é **1 acerto real + 1 indistinguível**. | Comparação do texto devolvido com o `legal_name` de entrada. |
| F17 | Estável e barato: 3 rodadas, saída byte a byte idêntica, **540 in / 120 out** e **US$ 0,000306** por rodada (6 lojas numa chamada). O teste inteiro custou US$ 0,0009 do orçamento dele. | Saída do script. |

### 7.5 O achado principal: registro e IA são complementares, não redundantes

| Loja | Registro de CNPJ | IA | União |
|---|---|---|---|
| SENDAS DISTRIBUIDORA S/A | vazio | **Assaí Atacadista** | ✅ |
| COMERCIAL DE ALIMENTOS HTP LTDA | **SUPERMERCADO VENEZA** | recusou | ✅ |
| COSTA MULTICANAL S/A | **COSTA ATACADAO** | recusou | ✅ |
| DONA DE CASA S/A (×2) | DONA DE CASA | Dona de Casa | ✅ |
| **Cobertura** | **4 de 5** (2 úteis, 2 redundantes) | **2 de 5** (1 útil, 1 indistinguível) | **5 de 5** |

| # | Fato | Evidência |
|---|---|---|
| F18 | **Nenhuma das duas fontes sozinha cobre as 5 lojas; a união cobre todas.** E onde uma acerta, a outra tipicamente falha — a correlação é inversa, não sobreposta. | Tabela acima. |
| F19 | A razão é estrutural, e é o que faz esperar que o padrão se mantenha em loja nova: o mercadinho local **declara** o fantasia no registro (é o único lugar onde está escrito) e ninguém fora do bairro o conhece → o registro ganha. A rede nacional tem marca de conhecimento público mas o campo da filial fica em branco → a IA ganha. As duas fontes cobrem os dois extremos do mesmo eixo. | *Inferido* a partir de F10/F11/F14, não medido em amostra maior. |
| F20 | A ordem "registro primeiro, IA só quando vier vazio" casa com a regra de frequência que o projeto já impõe à IA (só em ponto de baixa frequência) e foi medida: o registro veio vazio em **1 de 5** lojas, então a IA seria chamada para 1 loja — custo na casa de US$ 0,00005 por loja nova. | F10 + F17. |

## 8. O que foi construído (17/09/2026)

Sem migração: o apelido composto mora em `stores.nickname`, que já existe.

| Peça | Papel |
|---|---|
| `domain/normalization.py::store_place` | o bairro, segmento `[-3]`, ancorado à direita (RNF2) |
| `domain/normalization.py::compose_nickname`/`is_unnamed` | a **única** definição de como um apelido é composto e de quem está pendente — a dica e a nomeação consultam a mesma regra, então não podem discordar |
| `infra/cnpj_client.py::fetch_trade_name` | uma API (BrasilAPI), `urllib` da stdlib, sem dependência nova; toda falha lê como "sem nome fantasia" |
| `services/suggestions.py` prompt `store` + `suggest_trade_names` | a segunda fonte, pelo `_ask` que já cuida de orçamento, retry e log |
| `services/catalog.py::name_stores`/`unnamed_stores` | a ordem medida (registro → IA), a composição e a gravação |
| `cli/stores.py::revisar` | o comando; grava a ação em `actions.jsonl` com o desfazer |
| `cli/receipts.py::_name_stores` | o mesmo, dentro do `importar`, **só com o registro** (ver Q5) |

**Rodada real (contra cópia do banco de produção).** Das 5 lojas, 4 já tinham apelido dele e **nenhuma foi tocada** (RF2). A única pendente era a da F8:

```
20209736000181  SUPERMERCADO VENEZA   registro do CNPJ
```

E `consultar contra file` passou a mostrar `SUPERMERCADO VENEZA` no lugar de `COMERCIAL DE ALIMENTOS HTP LTDA` — que é exatamente onde a reclamação aparecia (RF8). Devolvendo o Assaí ao estado "sem apelido" para exercitar a segunda fonte:

```
06057223052643  Assaí Atacadista — St Complementares   IA
```

As duas fontes, as duas cobrindo o que a outra não cobre, no banco de verdade.

**Dois defeitos que os testes acharam, registrados porque são o tipo de coisa que volta.**
1. **O apelido provisório engolia o nome fantasia para sempre.** Nomear só com o bairro fazia `nickname != legal_name`, então a loja parecia pronta e o registro nunca era consultado de novo — uma falha de rede passageira custaria o nome definitivamente. Corrigido em `is_unnamed` (Q2), com teste próprio.
2. **`fetch_trade_name` como valor default de parâmetro era impossível de substituir.** Default é avaliado uma vez, no import, então o `monkeypatch` do `conftest` não pegava e **a suíte inteira estava consultando a API de verdade** (103 s de rodada; 11 s depois). Corrigido para resolver pelo módulo na hora da chamada, mais um `_no_cnpj_lookup` autouse no `conftest` — a mesma disciplina que já isolava as credenciais de IA.

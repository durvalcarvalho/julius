# Design: voz do fallback e reconhecimento de contexto (Casos 1, 2, 3, 5)

> Desenho de `docs/requirements/bot-persona-fallback-improvements.md` §10 — os quatro casos que sobreviveram depois de §4.1 (preço avulso) ser rejeitado. **Sem arquitetura nova**: nenhuma migração, nenhuma tabela, nenhuma ação de escrita, nenhum dataclass novo. É texto em, no máximo, três arquivos já existentes — o valor deste desenho é dizer exatamente onde e por quê, não inventar componente.

## 0. Achado que muda a prioridade: Caso 1 tem duas causas possíveis, não uma

Antes de tocar em qualquer prompt, vale registrar o que a leitura de `bot/turn.py` mostrou e que o documento de requisitos não sabia ainda: **a busca sem resultado já passa pela IA hoje**, não é um caminho puramente determinístico.

```python
# bot/turn.py::_render_no_match
facts = no_match_facts(output.term, alternatives)
remark = await _narrate(deps, "busca sem resultado", facts)
if remark:
    return Reply(remark)
return Reply(no_match_fallback_line(output.term, alternatives))  # só cai aqui se narrate() falhar/None
```

Ou seja, a frase robótica que o usuário viu repetida três vezes tem duas explicações possíveis, com remédios diferentes:

**(a) `narrate()` voltou `None` nas três vezes** (IA não configurada, orçamento estourado, erro de rede, ou resposta rejeitada pela guarda de dinheiro) — nesse caso, quem respondeu foi sempre `no_match_fallback_line` (render.py), que é **determinística por definição**: a mesma entrada sempre produz a mesma frase. Reescrever essa string com mais tom resolve a *qualidade* de uma ocorrência, mas **não resolve a repetição** — a frase nova, por melhor que seja, vai se repetir palavra por palavra todo dia, e no terceiro uso vai soar tão robótica quanto a de hoje.

**(b) `narrate()` funcionou, mas o contexto "busca sem resultado" saiu genérico mesmo assim** — medido: o prompt `persona` (`services/suggestions.py`) tem **6 pares de exemplo de entrada/saída**, um para cada outro contexto (histórico de um produto, vários produtos, vários sem padrão, veredito de lista, conferência de preço com/sem veredito) — e **nenhum para "busca sem resultado"**. Esse contexto vive só da regra genérica "não explique a ausência, comente só com o que tem" (linha 210-212), sem exemplo pra imitar. Este projeto já aprendeu essa lição mais de uma vez (v2.8: "só a instrução em prosa não bastou") — é a explicação mais plausível pra "voz sumindo" quando a IA está de fato respondendo.

**Diagnóstico antes do remédio** (decisão já tomada em §9 do requisito: medir com `make test-ia` antes de mudar prompt): forçar um caso de zero-resultado na suíte `real_ai` e olhar `ai_calls.jsonl` — se a chamada aparece lá com uma resposta, é (b); se a chamada nem aparece (ou aparece com erro), é (a). Os dois remédios abaixo não são mutuamente exclusivos — (a) é a rede de segurança que sempre deveria ter tom, (b) é o caminho principal — mas a ordem de prioridade depende de qual está realmente acontecendo na conversa real do usuário.

## 1. Caso 1 — os dois remédios

**Remédio A (`render.py::no_match_fallback_line`)**: reescrever a frase sem alternativas com tom Julius, mantendo a proibição de CTA (§9 do requisito — nunca pedir preço/mercado de volta). É uma função pura, testável por igualdade de string — o teste já existe (`test_render.py` ou equivalente) e só precisa do valor esperado atualizado.

**Remédio B (`services/suggestions.py::SYSTEM_PROMPTS["persona"]`)**: adicionar um sétimo par de exemplo, no mesmo formato dos outros seis, para o contexto `"busca sem resultado"` — fatos vindos de `no_match_facts` (`"produto pedido, sem preço registrado ainda: X"` + linhas de alternativas, se houver) → uma resposta que comenta sem explicar a ausência e sem pedir dado. Local exato: depois do último `"Exemplo de entrada (...)"` já existente no dicionário, antes do fechamento da string `"persona"`.

**Os dois entram juntos**, não como alternativa um do outro — (a) é sempre executado quando a IA falha (vai continuar acontecendo, orçamento estoura, rede cai), (b) é o que evita a "voz sumir" no caminho que hoje roda na maioria das vezes.

## 2. Casos 2, 3 e 5 — local exato: `bot/agent.py::SYSTEM_PROMPT`

Os três são regras de **roteamento** (decidir se chama uma ação ou responde em texto), não de narração — vivem no bloco `"Leitura:"` do `SYSTEM_PROMPT`, junto das regras já existentes de `search_prices`/`check_price` (linhas 76-95 hoje). Diferente do prompt `persona`, o `SYSTEM_PROMPT` de roteamento não usa o formato "Exemplo de entrada/saída" — é só prosa de regra. Isso é uma lacuna estrutural que vale nomear: se a mesma lição do §0(b) se aplicar aqui (regra em prosa não basta), o prompt de roteamento pode precisar ganhar o mesmo formato de exemplo que o `persona` já tem — decisão a confirmar na implementação, não neste desenho, mas a suíte `ROUTING_CASES` (abaixo) é o que vai revelar se a prosa sozinha bastou.

- **Caso 5** (menor risco): estender a regra que já existe hoje ("está caro? sem preço dito não é veredito seu: chame search_prices...") com a condição "se nem a mensagem atual nem o histórico trouxerem um item, pergunte qual item antes de chamar qualquer ação". Uma frase a mais na regra existente, não uma regra nova.
- **Caso 2** (risco médio, ver §10 do requisito para o gatilho/não-gatilho exato): regra nova, depois do bloco de `check_price`. Contrato: usar o histórico de 3 turnos pra checar se a última fala do bot foi retórica/brincadeira antes de tratar a mensagem como pedido de preço.
- **Caso 3** (risco mais alto — histórico do projeto já mostrou bug de desempate nesta mesma vizinhança, v2.11 tomate/passata): regra nova, mesmo bloco. Contrato: ligar duas menções consecutivas só quando a segunda é variação explícita de embalagem/tamanho da primeira, nunca produtos de `kind` diferente.

## 3. Contrato de aceitação — obrigatório antes de fechar qualquer texto de prompt

Reaproveitando §10 do documento de requisitos, não repetindo aqui: cada um dos quatro casos precisa de uma entrada em `tests/test_real_ai.py::ROUTING_CASES` cobrindo o exemplo já escrito lá (a piada da luz, a coca→coca 2L, a pergunta vaga, o zero-resultado) antes de considerar o prompt pronto — "ler bem" não é critério de aceite neste projeto, `make test-ia` é.

## 4. O que este desenho confirma que NÃO muda

Nenhuma migração, nenhuma tabela, nenhum dataclass em `domain/models.py`, nenhuma ação nova em `bot/actions.py`, nenhum repositório novo. Os únicos arquivos tocados: `julius/bot/agent.py` (SYSTEM_PROMPT), `julius/services/suggestions.py` (SYSTEM_PROMPTS["persona"], `PROMPT_VERSIONS["persona"]` sobe pra próxima versão), `julius/bot/render.py` (uma string). `PROMPT_VERSIONS`/versionamento de prompt já é convenção existente (persona está em "6" hoje, segundo o histórico do `CLAUDE.md`) — subir a versão é o único "schema change" que existe aqui, e é dado, não DDL.

## 5. Rodada real (2026-09-22, implementado e medido nesta sessão)

Os quatro casos foram implementados (`bot/agent.py::SYSTEM_PROMPT` v3, `services/suggestions.py::SYSTEM_PROMPTS["persona"]` v7, `bot/render.py::no_match_fallback_line`) e medidos contra o modelo de verdade (`make test-ia`): **26 chamadas, ~US$ 0,04**, suíte determinística inteira (1170 testes) verde.

**14 de 15 testes novos passaram de primeira.** Dois achados que valem registrar:

1. **A suíte `real_ai` nunca tinha testado a narração da persona, só o roteamento.** A fixture `deps` compartilhada do arquivo nunca passa `client=`, e `_render_output`/`_render_no_match` tratam `deps.client is None` como "sem narração" — coerente com o propósito declarado do arquivo ("Roteamento: medido e reportado"), mas isso significava que nenhum teste ali jamais tinha exercitado `SYSTEM_PROMPTS["persona"]` de verdade. O teste do Caso 1 precisou montar seu próprio `Deps` com `HttpLlmClient.from_config()` para validar os dois remédios de ponta a ponta — sem isso, o teste passaria trivialmente (`"Nenhum resultado."` óbvio não tem CTA) sem provar nada. Resultado real: *"Feijão eu ainda não tenho na conta.\n\nMas já que veio a lista: [3 alternativas com preço]...\n\nGeleia a R$ 19,99? Isso não é geleia, é investimento."* — narração da persona, com voz, sem pedir preço/mercado de volta.
2. **Caso 3 falhou, e o motivo é do catálogo, não do prompt.** Medido: os 4 refrigerantes reais (`products` table) sempre têm o tamanho no `canonical_name` (Pepsi 2L, Guaraná 1,5L, duas Coca 1,5L) — não existe "coca sem tamanho" neste catálogo. O teste real (turno 1 "quanto paguei de coca?" → mostrou 1,5L; turno 2 "e o refrigerante de 2 litros?" → buscou direto, achando o Pepsi 2L de verdade) expôs que a premissa do caso ("tamanho ainda não dito") é mais rara na prática do que a conversa original sugeria — buscar direto não é claramente errado quando o tamanho pedido também existe de verdade. Marcado `xfail` com o achado completo no motivo, não escondido nem forçado a passar; decisão de reforçar mais o prompt ou aceitar como limite conhecido fica para o usuário.

## 6. Próximo passo

`/sc:implement`, com o diagnóstico do §0 como primeiro passo runtime (não código): rodar `make test-ia` com um caso de zero-resultado antes de escrever o remédio B, pra confirmar que vale a pena. Depois, na ordem de menor pra maior risco: Caso 5 → Caso 1 (A+B) → Caso 2 → Caso 3, cada um fechando com sua entrada em `ROUTING_CASES` antes do próximo.

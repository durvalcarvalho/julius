# 172: prompt `persona` v3 — veredito, lista negra e exemplo trabalhado

> A reescrita que devia ter vindo com exemplo desde o início: "compra em X"/"não compra em Y" quando há 2+ mercados, lista negra de conectivo de redação, e o primeiro exemplo de entrada/saída que este prompt ganha — os outros 5 prompts do projeto já têm, `persona` era o único sem.

## Contexto

Segue o design v2.7.1, em cima do prompt v2 (ticket 163, revisado). Depende de **170**/**171** (o exemplo do prompt usa `weekday_phrase` e fatos deduplicados — precisa que os fatos já venham no formato novo pra o exemplo bater com a realidade).

## Escopo

### Dentro
- `SYSTEM_PROMPTS["persona"]` reescrito (v3):
  - Mantém tudo do v2 que já funcionou: estrutura em duas partes (informação primeiro, comentário depois), guarda de dinheiro (nunca somar/subtrair, só copiar valor dos fatos), nunca afirmar escrita já feita, nunca explicar ausência de dado.
  - **Novo — veredito**: quando os fatos trazem 2 ou mais mercados para o mesmo produto (ou grupo, no caso de comparação), a resposta fecha com uma recomendação direta ("compra em X" / "não compra em Y" ou equivalente) apontando o mercado do menor preço dado. Com um só registro (nada pra comparar), sem veredito.
  - **Novo — lista negra explícita**: "além disso", "portanto", "em suma", "é importante destacar", "vale ressaltar" (e variações óbvias) nunca aparecem.
  - **Novo — exemplo de entrada/saída**, no mesmo formato que `enrich`/`merge`/`packaging`/`store`/`match` já usam neste arquivo: fatos de cebola (2 mercados, `weekday_phrase`, diferença já calculada) → resposta em 3 blocos curtos com `\n\n` entre eles, terminando no veredito. Ver o texto exato combinado no design (seção 3), não reformule à toa — é a âncora do tom que duas rodadas de instrução solta não fixaram.
- `PROMPT_VERSIONS["persona"]` → `"3"`.
- Reavaliar `max_tokens` da chamada em `narrate()` (hoje 380, subiu pra respostas mais longas no v2) — o pedido desta rodada é o oposto, respostas mais curtas; ajustar pra baixo (chute razoável: 260) e confirmar no smoke (174).

### Fora
- Qualquer mudança em `narrate()` além do `max_tokens` — a função em si (guarda, `_ask`, assinatura) não muda.
- Erro + autocorreção — fora desta rodada por decisão (ver brainstorm v2.7.1); não adicionar instrução nenhuma sobre isso.
- Calibração de ritmo por teste A/B — o exemplo trabalhado é a tentativa desta rodada; não monte infraestrutura de teste A/B agora.

## Requisitos

### Funcionais
- O veredito só aparece com 2+ mercados/entradas comparáveis nos fatos — não é uma frase fixa acoplada ao template, é uma instrução condicional que o modelo aplica lendo os fatos.
- O exemplo de saída no prompt usa quebras de linha reais dentro da string JSON (`\n\n`, que o JSON já suporta) — é o que ensina o formato de blocos curtos, não uma instrução em prosa sozinha (que já foi tentada nas duas rodadas anteriores sem fixar o ritmo).
- A guarda de dinheiro (`narrate()`, ticket 163) não muda — o exemplo do prompt precisa ser 100% consistente com ela: todo valor que aparece no "Exemplo de saída" tem que estar literalmente no "Exemplo de entrada".

### Validação e erros
- Nenhuma mudança de assinatura em `narrate()`, só o valor de `max_tokens` passado pra `_ask`.

## Especificação técnica

```
modificar julius/services/suggestions.py — SYSTEM_PROMPTS["persona"] (v3), PROMPT_VERSIONS["persona"] = "3", max_tokens em narrate()
modificar tests/test_services_suggestions.py — prompt_version esperado (já usa suggestions.PROMPT_VERSIONS["persona"], não precisa mudar o valor no teste)
```

### Padrão a seguir
- `SYSTEM_PROMPTS["enrich"]` (mesmo arquivo): formato exato de "Exemplo de entrada:" / "Exemplo de saída:" a copiar.
- O comentário acima de `"persona"` no dicionário já registra o histórico de por que o prompt mudou (v1→v2) — continuar esse padrão, uma linha por versão, não apagar o que já está lá.

## Testes obrigatórios

1. `test_narrate_returns_grounded_text` (já existe) — continua verde; `prompt_version` já é lido de `suggestions.PROMPT_VERSIONS["persona"]`, não precisa de edição.
2. Nenhum teste unitário novo é estritamente necessário aqui (o conteúdo do prompt não é testável por unidade além do que `narrate()` já cobre) — a validação real deste ticket é o smoke (174).
3. Suíte inteira (`.venv/bin/pytest -q`) continua verde.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde.
- [ ] `grep -n '"3"' julius/services/suggestions.py` mostra `PROMPT_VERSIONS["persona"]`.
- [ ] `grep -n "Exemplo de entrada" julius/services/suggestions.py` mostra 6 ocorrências (as 5 de sempre + `persona`).
- [ ] Todo valor monetário no "Exemplo de saída" do prompt `persona` aparece literalmente no "Exemplo de entrada" dele (conferência manual — é exatamente a regra que a guarda de `narrate()` aplicaria em produção).

## Notas para o agente

- Não invente uma segunda versão do exemplo "pra cobrir mais casos" — um exemplo bem escolhido (o da cebola, que é o caso real que motivou a rodada) é o suficiente; mais exemplos custam tokens de entrada em toda chamada, pra um ganho que a v2 já mostrou ser incerto sem medir.
- `max_tokens = 260` é chute — o valor real de saída no smoke (174) decide se sobra ou falta espaço; não trate 260 como medido.

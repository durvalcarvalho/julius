# Rastreador da sessão — 2026-09-19

> Documento de trabalho, não é requisito nem design. Todas as frentes abaixo fecharam nesta sessão — mantido como registro, não precisa mais ser atualizado a cada passo.

## Frentes — todas fechadas

### 1. `shopping-verdict-shape` — veredito de compra (ordem, item que some, `check_price`, categoria)
- **Status: implementado, testado, validado com IA real, no ar em produção.**
- Docs: `docs/requirements/shopping-verdict-shape.md`, `docs/design/shopping-verdict-shape.md`. `CLAUDE.md` v2.11.
- Rodada real (`make test-ia`): 9 testes, 16 chamadas, US$ 0,0173, roteamento 6/6 (100%) — confirmou ao vivo a resposta abrindo com a instrução ("Compra no Costa Atacadao pra cebola e tomate...").
- `check_price` (RF4) ainda não tem caso de rota em `ROUTING_CASES` — não foi exercitado pela IA real ainda, fica pra próxima rodada se quiser fechar isso também.

### 2. `agent-output-honesty` — o bot nunca mais afirma o que não checou
- **Status: implementado, testado, validado com IA real, no ar em produção.**
- Doc: `docs/design/agent-output-honesty.md`. `CLAUDE.md` v2.12.
- `temperature=0.0` + guarda `@agent.output_validator` + log do texto real + `except UnexpectedModelBehavior` específico + `pydantic-ai` fixado em `2.45.0`.
- Rodada real: guarda nunca disparou nas 16 chamadas (nenhum falso positivo), roteamento 100%.
- **Achado da própria rodada real**: a correção de log (texto real em vez de `"text"`) quebrou a comparação por igualdade do teste de roteamento — corrigido (`_is_free_text`, compara por "não é nome de ação conhecido"). Registrado no `CLAUDE.md` como lição: teste que lê log de produção quebra quando o log melhora.

### 3. Bot em produção
- **Status: reiniciado às 22:36 com o código das duas frentes + versão 2.12.0.** `make install-bot` (pin do `pydantic-ai-slim==2.45.0` respeitado, já estava nessa versão) + `julius-bot` em background. Rodando limpo (`Julius no ar, ouvindo o chat 647689002`).

### 4. `pyproject.toml` versão
- **Status: corrigido.** `0.1.0` → `2.12.0`, acompanhando o `CLAUDE.md`. Lembrete pra próxima rodada: bater essa linha de novo não é automático.

## O que ainda depende de você

- **Roteiro manual pelo Telegram** (`docs/como-testar-o-bot.md`) — a única verificação que exige você mesmo interagindo com o bot de verdade (ex.: "os ovos tão 14 reais, tá bom?" pra confirmar `check_price` na prática, e conferir se a resposta de lista de compras realmente lê bem pra você).

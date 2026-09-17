# 145: CLI — a linha que responde "qual embalagem compensa"

> Em vez de o usuário ler a coluna e ordenar de cabeça, `consultar` diz qual sai mais barato na unidade base.

## Contexto

`docs/design/merge-and-unit-price-v2.4.md` §6.3. Requisitos RF11/RF12 e a questão Q6.

O cálculo já existe e já está correto (F7): no banco real, a `Água mineral Indaiá 1,5L` a R$ 3,69 já é marcada como a mais barata porque sai a R$ 2,46/L contra R$ 2,98/L da Crystal 500ml. O que falta é dizer isso.

Depende de **144** (a ordem por conteúdo).

## Escopo

### Dentro
- `julius/cli/receipts.py`: a linha de resposta depois da tabela de cada unidade.
- `tests/test_cli_receipts.py` (é onde `consultar` é testado).

### Fora
- Qualquer veredito de barato/caro, tendência, média ou previsão (RF12) — a frase declara uma ordenação de fatos do que foi comprado.
- Repetir a frase em `mercados comparar` (Q6: ele já responde por construção, com o mais barato em verde e a contagem por grupo).
- Mudar `search_prices`/`records_for_products` (fechados no 144) ou qualquer contrato de serviço.

## Requisitos

### Funcionais

- Depois de imprimir a tabela de uma unidade, e **só** quando `comparison_basis` daquele grupo devolveu `price_per_content` e há ao menos duas linhas participantes, imprimir uma linha:

```
Mais barato por litro: Água mineral Indaiá 1,5L a R$ 2,46/L — a Água Crystal sem gás 500ml sai a R$ 2,98/L.
```

  - nomeia o mais barato e o mais caro **do que foi comprado**, com os dois preços na unidade base;
  - "por litro"/"por quilo"/"por unidade" conforme `content_unit` (L/KG/UN), em português;
  - usa o `highlight` que já está nos registros: nenhum cálculo novo;
  - empate entre o menor e o maior (todos iguais): não imprime.
- Grupo em série temporal (um produto só), grupo KG, ou grupo sem conteúdo suficiente: nada é impresso.
- A linha é discreta, no estilo das dicas (`dim`), mas **não** é uma `Hint`: sai em toda consulta com resultado comparável, e o módulo de dicas só dispara em vazio/erro/primeira vez.

### Validação e erros
- Nunca muda o código de saída.
- Nunca lança: registro sem `content_unit` ou sem par comparável simplesmente não gera a linha.

## Especificação técnica

```
modificar julius/cli/receipts.py
modificar tests/test_cli_receipts.py
```

### Padrão a seguir
- A CLI pode importar `domain` (a DAG permite `cli → domain`), então chame `comparison_basis` diretamente sobre os registros da unidade — nenhum serviço muda.
- `money()` de `cli/_common.py` formata o valor em reais com vírgula; use-o para os dois preços.
- `console.print(..., style="dim")` como as dicas fazem.

## Testes obrigatórios

1. `test_consultar_prints_the_cheapest_per_litre` — a saída contém "Mais barato por litro", o nome do produto de 1,5L e os dois preços por litro.
2. `test_consultar_says_quilo_and_unidade` — grupos com `content_unit` KG e UN → "por quilo" e "por unidade".
3. `test_consultar_no_line_for_time_series` — histórico de um produto só → a frase não aparece.
4. `test_consultar_no_line_for_kg_group` — grupo vendido por KG → não aparece.
5. `test_consultar_no_line_when_only_one_has_content` — menos de duas linhas comparáveis → não aparece.
6. `test_consultar_no_line_when_all_prices_are_equal` — empate → não aparece.
7. `test_consultar_line_does_not_change_exit_code` — código 0 com e sem a frase.

## Critérios de aceite
- [ ] `.venv/bin/pytest -q` verde (suíte inteira).
- [ ] `grep -rn "Mais barato por" julius/services julius/domain` **vazio** — a frase é apresentação e vive só na CLI.
- [ ] Rodar contra uma cópia do banco real: `julius consultar agua` termina com a frase citando a Indaiá 1,5L a R$ 2,46/L.
- [ ] `tests/test_architecture.py` verde sem edição.

## Notas para o agente
- Não transforme isso numa `Hint`: o módulo de dicas tem três gatilhos (vazio, erro, primeira vez) e no máximo 2 por comando; esta linha é o resultado normal do comando, não um diagnóstico.
- Não escreva "caro" nem "barato" sobre o preço em si — só a comparação entre as embalagens que o usuário comprou (RF12).

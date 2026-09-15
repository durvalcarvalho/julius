.PHONY: install uninstall test

# `julius` global (~/.local/bin) apontando pro código deste diretório: editar ou trocar
# de branch já muda o comando instalado. Rode de novo só se o pyproject.toml mudar.
install:
	pipx install --force --editable .

uninstall:
	pipx uninstall julius

.venv/bin/pytest:
	python3 -m venv .venv
	.venv/bin/pip install -e '.[dev]'

test: .venv/bin/pytest
	.venv/bin/pytest -q

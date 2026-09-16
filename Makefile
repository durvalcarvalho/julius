.PHONY: install uninstall test inbox

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

# `entrada/` é um symlink pra pasta canônica: o Ctrl+S do navegador cai aqui e o arquivo
# já está fisicamente no lugar certo — não há nada a mover depois.
inbox:
	mkdir -p ~/.local/share/julius/entrada
	ln -sfn ~/.local/share/julius/entrada entrada

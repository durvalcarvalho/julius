import typer

app = typer.Typer(
    help="Julius — memória de preços de mercado a partir de recibos NFC-e.",
    no_args_is_help=True,
)


# An explicit callback keeps `julius` a command group even while it has a single subcommand,
# so `julius importar x.html` never collapses into `julius x.html`.
@app.callback()
def _root() -> None:
    pass

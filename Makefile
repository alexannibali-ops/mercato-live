.PHONY: help install edizione demo serve check-sources test pulisci

help:
	@echo "make install        installa le dipendenze"
	@echo "make edizione       scarica i feed e impagina in docs/"
	@echo "make demo           impagina con dati finti (nessuna rete)"
	@echo "make serve          apre l'anteprima su http://localhost:8000"
	@echo "make check-sources  verifica che ogni feed in sources.yaml risponda"
	@echo "make test           controlla filtro, deduplica e punteggio"
	@echo "make pulisci        cancella build/ e docs/"

install:
	pip install -r requirements.txt

edizione:
	python src/fetch.py && python src/build.py

demo:
	python src/build.py --demo

serve:
	@echo "→ http://localhost:8000"
	@cd docs && python -m http.server 8000

check-sources:
	python src/check_sources.py

test:
	python tests/test_pipeline.py

pulisci:
	rm -rf build docs

.PHONY: ci format lint typecheck test dashboard fonts vendor-check serve

ci: format lint typecheck test

format:
	uv run ruff format --check src tests

lint:
	uv run ruff check src tests

typecheck:
	uv run ty check src

test:
	uv run pytest --doctest-modules --cov=verne80 --cov-report=term-missing

# Rebuild web/data/ from the pipeline's artefacts. The output is committed, so run this
# and commit the result alongside any change to places.csv — tests/test_dashboard_data.py
# fails if the two drift apart.
dashboard:
	uv run python scripts/08_dashboard.py

# One-off. The woff2 are committed, so this only runs when the type changes.
fonts:
	uv run python scripts/fetch_fonts.py

# The vendored modules must import each other and nothing else. tests/test_web_page.py
# asserts the same thing; this is the version you can read the output of.
vendor-check:
	@grep -o 'from *"[^"]*"' web/vendor/*.js | sort -u

serve:
	@echo "http://localhost:8000/"
	cd web && uv run python -m http.server 8000

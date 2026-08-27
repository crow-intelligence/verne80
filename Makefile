.PHONY: ci format lint typecheck test dashboard page publish fonts vendor-check serve

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

# The page is generated from the payloads and committed. Run after `make dashboard`,
# and commit both — tests/test_web_page.py fails if the two have drifted apart.
page:
	uv run python scripts/10_page.py

# Copy the page into the site repo, where the deploy's `cp -r` picks it up. The directory
# basename *is* the URL slug, so it is `verne`, not `verne80`. --delete, because a file
# removed here has to be removed there too.
SITE ?= ../crow-intelligence.github.io
publish: page
	rsync -a --delete web/ $(SITE)/projects/verne/
	@echo "  copied to $(SITE)/projects/verne/ — now commit it there"

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

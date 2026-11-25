.PHONY: all install run test typecheck build prewarm

all: install build

install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install

prewarm:
	cd backend && python -m app.scripts.prewarm

test:
	cd backend && pytest -m "not slow" -v

typecheck:
	cd frontend && npm run typecheck

e2e:
	cd frontend && npm run e2e

build:
	cd frontend && npm run build

run:
	bash start_app.sh

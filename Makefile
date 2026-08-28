.DEFAULT_GOAL := help
SHELL := /bin/bash
PY ?= python3
BACKEND := backend
FRONTEND := frontend

help:
	@echo "Maather Autonomous Trader"
	@echo "  make install      تثبيت اعتماديات الباك-إند والواجهة"
	@echo "  make test         تشغيل كل الاختبارات"
	@echo "  make run          تشغيل النظام كاملاً (API + واجهة)"
	@echo "  make run-api      الباك-إند فقط على 8000"
	@echo "  make run-ui       الواجهة فقط على 3000"
	@echo "  make feasibility  إعادة توليد تقرير جدوى رأس المال"
	@echo "  make verify-audit فحص سلامة سلسلة سجل التدقيق"
	@echo "  make backup       نسخة احتياطية مؤرخة من قاعدة البيانات"

install:
	$(PY) -m pip install -r $(BACKEND)/requirements.txt
	cd $(FRONTEND) && npm install

test:
	cd $(BACKEND) && $(PY) -m pytest -q

test-verbose:
	cd $(BACKEND) && $(PY) -m pytest -v

run-api:
	cd $(BACKEND) && $(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

run-ui:
	cd $(FRONTEND) && npm run dev

run:
	@echo "الباك-إند على 8000 والواجهة على 3000. اضغطي Ctrl+C للإيقاف."
	@trap 'kill 0' EXIT INT TERM; \
	( cd $(BACKEND) && $(PY) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 ) & \
	( cd $(FRONTEND) && npm run dev ) & \
	wait

feasibility:
	$(PY) scripts/capital_feasibility.py --write

verify-audit:
	$(PY) scripts/verify_audit_chain.py

backup:
	@mkdir -p backups
	@ts=$$(date +%Y%m%d-%H%M%S); \
	if [ -f data/maather.db ]; then \
	  cp data/maather.db backups/maather-$$ts.db && echo "backups/maather-$$ts.db"; \
	else echo "لا توجد قاعدة بيانات بعد في data/maather.db"; fi

typecheck:
	cd $(FRONTEND) && npx tsc --noEmit

build-ui:
	cd $(FRONTEND) && npm run build

.PHONY: help install test test-verbose run run-api run-ui feasibility verify-audit backup typecheck build-ui

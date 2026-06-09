up:
	docker compose -f infra/docker-compose.yml --env-file .env up -d

down:
	docker compose -f infra/docker-compose.yml --env-file .env down

logs:
	docker compose -f infra/docker-compose.yml --env-file .env logs -f

ps:
	docker compose -f infra/docker-compose.yml --env-file .env ps

restart:
	docker compose -f infra/docker-compose.yml --env-file .env restart

erp-up:
	docker compose -f services/erp/docker-compose.yml --env-file .env up -d

erp-down:
	docker compose -f services/erp/docker-compose.yml --env-file .env down

erp-logs:
	docker compose -f services/erp/docker-compose.yml --env-file .env logs -f backend

erp-init:
	bash services/erp/init-site.sh

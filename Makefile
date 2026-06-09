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

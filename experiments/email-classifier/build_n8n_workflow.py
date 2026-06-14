#!/usr/bin/env python3
"""
Генерирует n8n-воркфлоу автоклассификации писем (смотровой режим, промпт v2).
Пишет JSON в n8n-classifier-workflow.json. Публикация — отдельно, через
Public API n8n (см. README, ключ n8n на сервере).

Труба: расписание 15 мин → GET новых Communication из ERPNext (без классификации)
→ для каждого: текст в Claude (v2) → запись custom_claude_classification/_reason
обратно в карточку. НЕ создаёт лидов, оценку менеджера не трогает, идемпотентна.
"""
import json

ERP = "http://155.212.143.179:8080"
ACCOUNT = "PMK Park входящие (тест)"

SYSTEM_V2 = (
    "Ты классифицируешь входящие письма завода металлоконструкций (изготовление "
    "на заказ: просчёт → счёт → производство). Сначала определи РОЛЬ отправителя: "
    "это КЛИЕНТ (хочет, чтобы МЫ изготовили) или ПОСТАВЩИК/сторонний (предлагает "
    "НАМ товар/услугу)? Разложи письмо строго в ОДНУ из 5 полок.\n\n"
    "1. Новая заявка — КЛИЕНТ просит просчитать/выставить счёт/спрашивает о "
    "возможности изготовления (запрос КП, цены, позиции на просчёт).\n"
    "2. Вопрос по заказу — КЛИЕНТ про СВОЙ уже идущий заказ у нас («когда готово», "
    "ссылка на свой счёт/спецификацию). Только от клиента про его заказ.\n"
    "3. Поставщик — письмо ОТ поставщика: предлагает НАМ металл/трубы/прокат/"
    "метизы/комплектующие/услуги для производства («наличие», «прайс», «остатки», "
    "приглашение присылать ЕМУ заявки на закупку).\n"
    "4. Спам — массовая реклама/рассылки НЕ по нашему производству (реклама, SEO, "
    "банки, обучение, маркетинг, маркетплейсы), нерелевантные предложения.\n"
    "5. Прочее — служебное, ответы в переписке не про заявки, бухгалтерия, "
    "неопределённое.\n\n"
    "Жёсткие разграничения:\n"
    "- Поставщик vs Вопрос по заказу: письмо ОТ поставщика (наличие/прайс, "
    "приглашает присылать ему заявки) — это Поставщик, даже если есть слово "
    "«заявка»/«заказ». «Вопрос по заказу» — только клиент про СВОЙ заказ у нас.\n"
    "- Поставщик vs Спам: Поставщик — только профильный (металл/трубы/прокат/"
    "метизы/услуги для металлопроизводства). Нерелевантная реклама — Спам.\n"
    "- Игнорируй рекламные вставки внутри тела, если суть — реальный запрос "
    "клиента. Вложения ты НЕ видишь; классифицируй по теме+тексту. Если не уверен "
    "— «Прочее».\n\n"
    'Ответ строго JSON: {"shelf":"<одна из 5 точь-в-точь>","reason":"<1-2 фразы, укажи роль>"}'
)

# --- Code-узлы (jsCode) ---
PREP_JS = (
    "const it = $input.item.json;\n"
    "const strip = (h) => String(h||'').replace(/<[^>]+>/g,' ').replace(/\\s+/g,' ').trim();\n"
    "const body = strip(it.content).slice(0,2500);\n"
    "return { json: { name: it.name, userText: `Тема: ${it.subject||''}\\n\\nТекст:\\n${body}`, system: $json.__system } };"
)
# system пробрасываем через статическое поле — проще задать в самом узле:
PREP_JS = (
    "const SYSTEM = " + json.dumps(SYSTEM_V2, ensure_ascii=False) + ";\n"
    "const it = $input.item.json;\n"
    "const strip = (h) => String(h||'').replace(/<[^>]+>/g,' ').replace(/\\s+/g,' ').trim();\n"
    "const body = strip(it.content).slice(0,2500);\n"
    "return { json: { name: it.name, userText: 'Тема: ' + (it.subject||'') + '\\n\\nТекст:\\n' + body, system: SYSTEM } };"
)
PARSE_JS = (
    "const resp = $json;\n"
    "const text = (resp.content && resp.content[0] && resp.content[0].text) || '';\n"
    "const m = text.match(/\\{[\\s\\S]*\\}/);\n"
    "const SH = ['Новая заявка','Вопрос по заказу','Поставщик','Спам','Прочее'];\n"
    "let shelf='Прочее', reason='не распарсилось';\n"
    "if (m) { try { const o = JSON.parse(m[0]); shelf = SH.includes(o.shelf) ? o.shelf : (SH.find(s=>String(o.shelf||'').toLowerCase().includes(s.toLowerCase()))||'Прочее'); reason = String(o.reason||'').slice(0,500); } catch(e){} }\n"
    "const name = $('Подготовить текст').item.json.name;\n"
    "return { json: { name, shelf, reason } };"
)

CLAUDE_BODY = ("={{ JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 300, "
               "system: $json.system, messages: [{ role: 'user', content: $json.userText }] }) }}")

FILTERS = json.dumps([
    ["custom_claude_classification", "in", ["", None]],
    ["email_account", "=", ACCOUNT],
    ["sent_or_received", "=", "Received"],
    ["communication_type", "=", "Communication"],
], ensure_ascii=False)
FIELDS = json.dumps(["name", "subject", "content"], ensure_ascii=False)

nodes = [
    {"parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}},
     "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2,
     "name": "Каждую минуту", "position": [0, 300], "id": "n1"},

    {"parameters": {
        "method": "GET", "url": f"{ERP}/api/resource/Communication",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendQuery": True, "queryParameters": {"parameters": [
            {"name": "filters", "value": FILTERS},
            {"name": "fields", "value": FIELDS},
            {"name": "limit_page_length", "value": "20"}]},
        "options": {}},
     "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
     "name": "Новые письма из ERP", "position": [240, 300], "id": "n2"},

    {"parameters": {"fieldToSplitOut": "data", "options": {}},
     "type": "n8n-nodes-base.splitOut", "typeVersion": 1,
     "name": "По письмам", "position": [480, 300], "id": "n3"},

    {"parameters": {"jsCode": PREP_JS},
     "type": "n8n-nodes-base.code", "typeVersion": 2,
     "name": "Подготовить текст", "position": [720, 300], "id": "n4"},

    {"parameters": {
        "method": "POST", "url": "https://api.anthropic.com/v1/messages",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendHeaders": True, "headerParameters": {"parameters": [
            {"name": "anthropic-version", "value": "2023-06-01"},
            {"name": "content-type", "value": "application/json"}]},
        "sendBody": True, "specifyBody": "json", "jsonBody": CLAUDE_BODY,
        "options": {}},
     "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
     "name": "Claude классификация (v2)", "position": [960, 300], "id": "n5"},

    {"parameters": {"jsCode": PARSE_JS},
     "type": "n8n-nodes-base.code", "typeVersion": 2,
     "name": "Разобрать ответ", "position": [1200, 300], "id": "n6"},

    # Запись через whitelisted-метод saas_theme.api.set_classification —
    # пишет custom-поля в обход валидации Communication. REST PUT делал полное
    # сохранение документа → падал с InvalidEmailAddressError (HTTP 417) на
    # письмах с кривым адресом отправителя, и такие письма не классифицировались.
    {"parameters": {
        "method": "POST",
        "url": "=" + ERP + "/api/method/saas_theme.api.set_classification",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendBody": True, "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ name: $json.name, classification: $json.shelf, reason: $json.reason }) }}",
        "options": {}},
     "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
     "name": "Записать классификацию в ERP", "position": [1440, 300], "id": "n7"},
]

connections = {
    "Каждую минуту": {"main": [[{"node": "Новые письма из ERP", "type": "main", "index": 0}]]},
    "Новые письма из ERP": {"main": [[{"node": "По письмам", "type": "main", "index": 0}]]},
    "По письмам": {"main": [[{"node": "Подготовить текст", "type": "main", "index": 0}]]},
    "Подготовить текст": {"main": [[{"node": "Claude классификация (v2)", "type": "main", "index": 0}]]},
    "Claude классификация (v2)": {"main": [[{"node": "Разобрать ответ", "type": "main", "index": 0}]]},
    "Разобрать ответ": {"main": [[{"node": "Записать классификацию в ERP", "type": "main", "index": 0}]]},
}

workflow = {
    "name": "Автоклассификация писем (v2, смотровой режим)",
    "nodes": nodes,
    "connections": connections,
    "settings": {"executionOrder": "v1"},
}

with open("n8n-classifier-workflow.json", "w", encoding="utf-8") as f:
    json.dump(workflow, f, ensure_ascii=False, indent=2)
print("written n8n-classifier-workflow.json")

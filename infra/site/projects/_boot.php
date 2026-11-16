<?php
// Общий старт Bitrix из командной строки (контейнер site-web). Без вывода, без статистики, без агентов.
$_SERVER['DOCUMENT_ROOT'] = '/var/www/html';
$_SERVER['HTTP_HOST'] = 'pmkpark.ru';
$_SERVER['SERVER_NAME'] = 'pmkpark.ru';
$_SERVER['HTTPS'] = 'on';
define('NO_KEEP_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
define('NO_AGENT_CHECK', true);
define('NO_AGENT_STATISTIC', true);
define('BX_CRONTAB', true);
require $_SERVER['DOCUMENT_ROOT'] . '/bitrix/modules/main/include/prolog_before.php';
CModule::IncludeModule('iblock');
const PMK_PROJECTS_IB = 32;

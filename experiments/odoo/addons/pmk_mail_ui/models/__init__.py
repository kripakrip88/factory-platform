from . import mail_client_attachment
from . import mail_client_message
from . import ir_mail_server
from . import mail_thread
from . import mail_client_folder
from . import mail_client_flags
# Почта, остальное (разбор удобства, шаг 41): имена вложений, лид у строки,
# фильтр «С лидом», звезда переписки, счётчик новых.
from . import mail_client_step41
from . import ir_http
# Мелочи после приёмки 22–34 (шаг 53): папка письма для «Связей», адрес
# info@ → лиды выключен.
from . import mail_client_step53
# Ответ и пересылка из Odoo (редизайн почты, шаг 6; доска №40): кому отвечать
# на своё письмо, имя отправителя у ящика, время цитаты, вложения пересылки.
from . import mail_client_reply
# Карточка контрагента справа от письма (редизайн почты, шаг 7).
from . import mail_partner_card
# Окно «Новый лид из письма» (14.10.2026).
from . import mail_lead_draft

from django.core.mail import send_mail
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Сервис для отправки email уведомлений"""

    @staticmethod
    def send_password_reset_code(user, code):
        """Отправка кода сброса пароля"""
        try:
            subject = 'Код для сброса пароля - B2B Система'
            message = f"""
Здравствуйте, {user.name}!

Вы запросили сброс пароля для вашего аккаунта в B2B системе.

Ваш код для сброса пароля: {code}

Код действителен в течение 15 минут.

Если вы не запрашивали сброс пароля, просто проигнорируйте это письмо.
            """

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            logger.info(f"Код сброса пароля отправлен на {user.email}")
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки кода сброса пароля: {e}")
            return False

    @staticmethod
    def send_approval_notification(user, is_approved):
        """Уведомление об одобрении/отклонении заявки"""
        try:
            if is_approved:
                subject = 'Ваша заявка одобрена - B2B Система'
                message = f"""
Здравствуйте, {user.name}!

Ваша заявка на регистрацию в B2B системе была одобрена.

Теперь вы можете войти в систему и начать работу.

Добро пожаловать!
                """
            else:
                subject = 'Ваша заявка отклонена - B2B Система'
                message = f"""
Здравствуйте, {user.name}!

К сожалению, ваша заявка на регистрацию в B2B системе была отклонена.

Для получения дополнительной информации обратитесь к администратору.
                """

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            logger.info(f"Уведомление об {'одобрении' if is_approved else 'отклонении'} отправлено на {user.email}")
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")
            return False

    @staticmethod
    def send_welcome_email(user):
        """Приветственное письмо после регистрации"""
        try:
            subject = 'Добро пожаловать в B2B систему!'

            if user.role == 'partner':
                message = f"""
Здравствуйте, {user.name}!

Спасибо за регистрацию в нашей B2B системе.

Ваша заявка на регистрацию как партнёр передана на рассмотрение администратору.
Вы получите уведомление после проверки вашей заявки.
                """
            else:
                message = f"""
Здравствуйте, {user.name}!

Спасибо за регистрацию в нашей B2B системе.

Вы можете сразу начать пользоваться системой.
                """

            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=False,
            )

            logger.info(f"Приветственное письмо отправлено на {user.email}")
            return True

        except Exception as e:
            logger.error(f"Ошибка отправки приветственного письма: {e}")
            return False
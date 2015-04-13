from django.conf import settings
from django.core.mail import EmailMultiAlternatives


def send_email(receivers, subject, html_email, text_email, sender=settings.EMAIL_SENDER):
    """Simple utility function for sending an email through Django's backend which uses the Django email settings.
    :param receivers: A list of emails.
    :type receivers: list[str]
    :param subject: The email subject line.
    :type subject: str
    :param html_email: The HTML version of the email being sent.
    :type html_email: str
    :param text_email: The text version of the email being sent (it's just good practice).
    :type text_email: str
    :param sender: The email address that the email will appear to be sent from. Defaults to settings.EMAIL_SENDER
    :type sender: str
    """
    email = EmailMultiAlternatives(subject, text_email, sender, receivers)
    email.attach_alternative(html_email, 'text/html')
    email.send()

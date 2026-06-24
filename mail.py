import os
import logging
import resend

logger = logging.getLogger(__name__)

DEFAULT_FROM = 'Campus Plug <noreply@campusplug.com>'

def _init():
    api_key = os.environ.get('RESEND_API_KEY')
    if api_key:
        resend.api_key = api_key

def send_email(to, subject, html_body, from_addr=None):
    _init()
    if not resend.api_key:
        logger.warning('RESEND_API_KEY not set — skipping email')
        return
    try:
        resend.Emails.send({
            'from': from_addr or DEFAULT_FROM,
            'to': [to],
            'subject': subject,
            'html': html_body,
        })
    except Exception as e:
        logger.error(f'Failed to send email to {to}: {e}')

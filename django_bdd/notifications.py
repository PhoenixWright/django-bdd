import logging

from django.conf import settings
from s3util.s3util import S3Util
from django_bdd.email import send_email

from django_bdd.models import PASSED, FAILED  # for highlighting results

METRIC_EMAIL_RESULTS_SENT = u'EmailResultsSent'
METRIC_EMAIL_RESULTS_FAILURE = u'EmailResultsFailure'


log = logging.getLogger(u'django-bdd')


StatusColors = {
    PASSED: u'#00ff00',
    FAILED: u'#ff0000'
}


def get_status_color(status):
    # figure out what color the test status should be
    return StatusColors.get(status, u'#ffffff')


TEST_URL = u'{root}/bdd/tests/{test_id}/runs/{run_id}'
TEXT_EMAIL = u"""
BDD Test Results

{test_name}

Your test run completed in {test_duration} seconds:

{results}

You can view these results in more detail at: {url}

Thanks for using BDD!
"""

HTML_EMAIL = u"""\
<html>
    <head></head>
    <body>
        <h1>BDD Results</h1>
        <h2>{test_name} <span style="BACKGROUND-COLOR: {status_color}">[{test_status}]</span></h2>
        <h3>Your test run completed in {test_duration} seconds:</h3>
        <p>
            {results}
        </p>
        <p>You can view these results in more detail at: {url}</p>
        <p>Thanks for using BDD!</p>
    </body>
</html>
"""


def notify(test_run):
    """Builds a notification email for a test run and sends it.
    :param test_run: the test run object to send an email about
    :type test_run: TestRun
    """
    s3_util = S3Util(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_ACCESS_KEY, cloudwatch_namespace=settings.CLOUDWATCH_NAMESPACE)

    # validate the user to make sure we can even try to send an email
    user = test_run.user
    if not user:
        log.error(u"test has no user specified, can't send an email")
        s3_util.put_metric(METRIC_EMAIL_RESULTS_FAILURE, 1)
        return
    elif settings.EMAIL_DOMAIN not in user:
        user += settings.EMAIL_DOMAIN

    # query for the steps
    test_run_steps = test_run.testrunstep_set.all()

    text_results  = u'Step Results\n'
    text_results += u'------------\n'

    log.debug(u'building results emails')
    html_results = u'<ul>'  # the html results are an html list
    for step in test_run_steps:
        # add to the text results for the text email
        text_results += u'* {step_text} [{step_status}]\n'.format(step_text=step.text, step_status=step.status)

        # add to the html results for the html email
        html_results += u'<li>{step_text} <span style="background-color:{status_color}">[{step_status}]</span></li>'.format(
            step_text=step.text,
            status_color=get_status_color(step.status),
            step_status=step.status
        )
    # end the html list
    html_results += u'</ul>\n\n'
    log.debug(u'done building results emails')

    # build the url that links to the test run in the web ui
    url = TEST_URL.format(root=settings.ROOT_URL, test_id=test_run.test.id, run_id=test_run.id)

    # format the duration
    duration = (u'%.2f' % test_run.duration).rstrip(u'0').rstrip(u'.')

    # create the text email
    log.debug(u'formatting text email')
    text = TEXT_EMAIL.format(
        test_name=test_run.test.name,
        test_status=test_run.status,
        test_duration=duration,
        results=text_results,
        url=url
    )

    # create the html email
    log.debug(u'formatting html email')
    html = HTML_EMAIL.format(
        test_name=test_run.test.name,
        status_color=get_status_color(test_run.status),
        test_status=test_run.status,
        test_duration=duration,
        results=html_results,
        url=url
    )

    # set the receiver to the user who the test belongs to
    receivers = [user]
    subject = u'[BDD] Test Results for {test_name} [{test_status}]'.format(
        test_name=test_run.test.name,
        test_status=test_run.status
    )

    # actually send the email
    log.debug(u'calling send_email')
    send_email(receivers=receivers, subject=subject, html_email=html, text_email=text)
    log.debug(u'done sending email')

    # record a metric to track how many emails are getting sent
    s3_util.put_metric(METRIC_EMAIL_RESULTS_SENT, 1, dimensions={u'email': user})

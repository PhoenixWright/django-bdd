from django.db import models
from taggit.managers import TaggableManager


# statuses
NEW = 'new'
RUNNING = 'running'
PASSED = 'passed'
FAILED = 'failed'
ERROR = 'error'
SKIPPED = 'skipped'
STATUS_CHOICES = (
    (NEW, 'New'),
    (RUNNING, 'Running'),
    (PASSED, 'Passed'),
    (FAILED, 'Failed'),
    (ERROR, 'Error'),
    (SKIPPED, 'Skipped')
)


# Model Docs: https://docs.djangoproject.com/en/1.6/topics/db/models/

# blank:
# If True, the field is allowed to be blank. Default is False.
# Note that this is different than null. null is purely database-related, whereas blank is validation-related.
# If a field has blank=True, form validation will allow entry of an empty value.
# If a field has blank=False, the field will be required.


class Test(models.Model):
    # length 254 of user field decided by http://stackoverflow.com/questions/386294/what-is-the-maximum-length-of-a-valid-email-address
    user = models.CharField(max_length=254, help_text='The user who created (or edited) the test case.')
    name = models.CharField(max_length=600, blank=True, help_text='The name of the test case.')
    steps = models.TextField(blank=True, help_text='The sequential steps the test case follows.')

    # using django-taggit for tag support
    # getting started docs here: https://github.com/alex/django-taggit/blob/develop/docs/getting_started.txt
    # usage docs: https://github.com/alex/django-taggit/blob/develop/docs/api.txt
    # form usage: from taggit.forms import TagField; tags = TagField()
    # uses db tables named taggit_* created by running "./runpy manage.py syncdb"
    tags = TaggableManager(blank=True, help_text='A comma-separated list of tags.')

    class Meta:
        db_table = u'scenarios'

    def __unicode__(self):
        return u'%s - "%s" (%s)' % (
            self.id,
            self.name,
            self.user
        )


class TestRun(models.Model):
    test = models.ForeignKey(Test, on_delete=models.CASCADE, help_text='The test this test run is associated with.')
    user = models.CharField(max_length=254, help_text='The user who created the test run.')
    example_text = models.TextField(blank=True, help_text='The Behave Example: text to run the test with, if any.')
    timestamp = models.DateTimeField(null=True, blank=True, auto_now_add=True, help_text='The time the test run was created.')
    status = models.CharField(max_length=60, choices=STATUS_CHOICES, default=NEW, help_text='The current status of the test run.')
    text = models.TextField(blank=True, help_text='The report from Behave on what happened during the test.')
    duration = models.FloatField(default=0.0, help_text='How long the test took.')

    class Meta:
        db_table = u'scenario_runs'

    def __unicode__(self):
        return u'%s - "%s" - %s' % (
            self.id,
            self.test.name,
            self.status
        )


class TestRunStep(models.Model):
    """
    model for a test step in a test run
    """
    run = models.ForeignKey(TestRun, on_delete=models.CASCADE, help_text='The run this step result is associated with.')
    num = models.IntegerField(help_text='The order of the step in the test run.')
    example_row_num = models.IntegerField(default=1, help_text='The test permutation row number in the Behave example table.')
    text = models.TextField(blank=True, help_text='The step text.')
    status = models.CharField(max_length=60, choices=STATUS_CHOICES, default=NEW, help_text='The status of this particular step in a run.')
    timestamp_start = models.DateTimeField(null=True, blank=True, auto_now_add=True, help_text='The time the step began to run')
    timestamp_end = models.DateTimeField(null=True, blank=True, help_text='The time the step implementation completed.')
    duration = models.FloatField(default=0.0, help_text='How long the step took.')
    screenshot_s3_key = models.TextField(blank=True, help_text='S3 key for screenshot of step, if avail.')

    class Meta:
        db_table = u'scenario_run_steps'

    def __unicode__(self):
        return u'{} - {} - {} - {} - {}'.format(
            self.id,
            self.num,
            self.text,
            self.status,
            self.duration
        )


class TestEditHistory(models.Model):
    """
    model for test scenario edit history
    """
    test = models.ForeignKey(Test, help_text='The test this test version is associated with.')
    user = models.CharField(max_length=254, help_text='The user who created (or edited) the test case.')
    timestamp = models.DateTimeField(null=True, blank=True, auto_now_add=True, help_text='The time the test was edited.')
    version = models.IntegerField(default=1, help_text='The version number of the test history entry.')
    steps = models.TextField(blank=True, help_text='The step text for this version of the test.')

    class Meta:
        db_table = u'scenario_edit_history'

    def __unicode__(self):
        return u'{} - {} - {} - v{}'.format(
            self.id,
            self.test.name,
            self.user,
            self.version
        )

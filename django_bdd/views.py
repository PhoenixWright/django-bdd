import codecs
import logging
import re
import HTMLParser
import requests
from bs4 import BeautifulSoup

from django import forms

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core.urlresolvers import reverse
from django.db import connection
from django.db.models import Q  # for complex queries (including 'OR' logic)
from django.http import HttpResponse
from django.http.request import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape, strip_tags

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.renderers import JSONRenderer

from taggit.forms import TagField  # for letting users edit tags
from taggit.models import Tag

from django_tables2 import Table, TemplateColumn  # for displaying tables easily
from django_ajax.decorators import ajax  # for rendering dynamic forms like scenario outline textboxes
from tinymce.widgets import TinyMCE  # for editing scenario step text and autocomplete

from s3util.s3util import S3Util
from django_bdd.models import Test, TestRun, TestRunStep, TestEditHistory, NEW, RUNNING, FAILED,\
    PASSED, SKIPPED, ERROR
from django_bdd.serializers import TestSerializer, TestRunSerializer,\
    TestRunStepSerializer
from mobilebdd import runner

# Check out this URL for more info on potential method overrides:
# http://www.django-rest-framework.org/api-guide/viewsets

# create the s3 utilities
s3_util = S3Util(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_ACCESS_KEY, s3_bucket=settings.AWS_BUCKET)

# marker for dynamic fields in forms
DYNAMIC_FIELD_MARKER = u'dynamic_'

# mapping of run statuses to css classes
RunStatusClasses = {
    NEW: u'alert-info',
    RUNNING: u'alert-info',
    FAILED: u'alert-danger',
    PASSED: u'alert-success',
    SKIPPED: u'alert-warning',
    ERROR: u'alert-danger'
}

# mapping of test step statuses to css classes
StepStatusClasses = {
    NEW: u'text-muted',
    RUNNING: u'text-info',
    FAILED: u'text-danger',
    PASSED: u'text-success',
    SKIPPED: u'text-warning',
    ERROR: u'text-danger'
}

# list of label colors
LABEL_CLASSES = [
    u'label-default',
    u'label-primary',
    u'label-success',
    u'label-warning',
    u'label-danger',
    u'label-info'
]

log = logging.getLogger(u'django-bdd')


def get_user(request):
    """given a web request, attempts to pull 'REMOTE_USER' out of the request
    :return: the user. defaults to 'nobody'
    """
    user = request.environ.get(u'REMOTE_USER', u'nobody')
    if user == u'nobody':
        log.error(u'user not detected through REMOTE_USER environment variable')
    return user


def steps_to_html(steps):
    # TinyMCE puts these characters there instead of spaces
    steps = steps.replace(u' ', u'\xa0')

    # escape any characters that would get lost on a web page
    html = escape(steps)

    # create one 'p' tag for every line in the steps field to show newlines on page accurately
    html = u'<p>' + u'</p>\n<p>'.join(html.splitlines()) + u'</p>'

    return html


def html_to_steps(html):
    # get rid of the html tags
    steps = strip_tags(html)

    # unescape the string to get &, <, >, etc.
    html_parser = HTMLParser.HTMLParser()
    steps = html_parser.unescape(steps)

    # TinyMCE puts these characters there instead of spaces
    steps = steps.replace(u'\xa0', u' ')

    return steps


def filter_tags(test_queryset, tags):
    """
    @param test_queryset: a Test object query set
    @type test_queryset: QuerySet
    @param tags: list of tags
    @type tags: list
    """
    # create a list of test ids to remove from the query set
    to_remove = []
    tags = set(tags)
    for test in test_queryset:
        test_tags = set(test.tags.names())
        if not tags.issubset(test_tags):
            to_remove.append(test.id)

    # exclude the ids from the query set
    test_queryset = test_queryset.exclude(id__in=to_remove)
    return test_queryset


class JSONResponse(HttpResponse):
    """
    An HttpResponse that renders its content into JSON.
    """
    def __init__(self, data, **kwargs):
        content = JSONRenderer().render(data)
        kwargs[u'content_type'] = u'application/json'
        super(JSONResponse, self).__init__(content, **kwargs)


@ajax
def delete_modal(request, test_id=None):
    """Returns the html for the modal that includes a delete button for
    deleting a scenario. Called by the scenario list view to display this modal
    when the delete buttons are clicked.
    """
    log.debug(u'delete_modal')

    if not test_id:
        return u'Error: no test id provided to delete_model'

    test = Test.objects.get(pk=test_id)

    header_text = u'Are you sure?'
    content_text = u'Are you sure you wish to delete "{}"?'.format(test.name)
    left_button_text = u'Cancel'
    right_button_text = u'Delete'
    right_button_link = reverse(u'bdd-delete-test',  args=(test_id,))

    return render(request, u'django_bdd/modal.html', {
        u'header_text': header_text,
        u'content_text': content_text,
        u'left_button_text': left_button_text,
        u'right_button_text': right_button_text,
        u'right_button_link': right_button_link
    })


@ajax
def scenario_outline_example_form(request, test_id=None):
    """The entire purpose of this method is to render a scenario outline's
    Example: in django Form format so that the user can edit some textboxes rather
    than create the Example table embedded within the scenario.

    :return: Either a rendered form or None if the form was not necessary.
    """
    log.debug(u'scenario_outline_example_form')

    if not test_id:
        return u'Error: no test id provided to scenario_outline_example_form'

    # get the variables in the test steps if there are any
    variables = []

    # get the test object and its steps
    test = Test.objects.get(pk=test_id)
    steps = test.steps

    # inspect the steps to see if we need to look for variables
    if u'Examples:' in steps:
        return None  # nothing needs to be rendered because Examples are embedded in the scenario text

    # find all instances of brackets in the text and create fields for those items
    # [^\>\n\r]+
    # is one or more characters (+) that ARENT a >, newline, or carriage return
    # [] is a character class, means anything inside
    # adding a ^ negates the class
    # [^abc] means anything NOT a, b, or c
    variables = re.findall(r"\<([^\>\r\n]+)\>", steps)

    if not variables:
        log.debug(u'no variables found in steps for test {}'.format(test.id))
        return None  # nothing needs to be rendered because there are no variables in the scenario text
    else:
        log.debug(u'found varibles for test {}: {}'.format(test.id, variables))

    # create dynamic args to pass into the form
    kwargs = {}
    for variable in variables:
        kwargs[DYNAMIC_FIELD_MARKER + variable] = variable
    form = ScenarioOutlineExampleForm(**kwargs)
    return render(request, u'django_bdd/bddscenariooutlineform.html', {u'test': test, u'form': form})


def get_step_variables(steps):
    """
    extracts any <xyz> style text from a bdd scenario. these are the variables
    for a scenario outline.

    @param steps: bdd scenario outline steps text
    @type steps: unicode
    @return: the parsed out set of variable names
    @rtype: set(basestring)
    """
    return set(re.compile(r'<([^<>\n\r>]+)>').findall(steps))


def form_examples(request, step_variables):
    """
    extract the examples from the request data, if possible

    @param request: http request object
    @type request rest_framework.request.Request
    @param step_variables: set of variable names from the bdd test
    @type step_variables: set(basestring)
    @return: none if no examples or failed, or formed examples and an error msg,
        if applicable
    @rtype: (basestring, basestring)
    """
    if u'examples' not in request.DATA:
        return None, None

    examples = request.DATA[u'examples']
    log.debug(u'request has examples:\n{}'.format(examples))

    # examples should be an array of json objects, each object being an
    # example row
    if not isinstance(examples, list):
        return None, u'examples payload was not an array'
    if not examples:
        return None, u'examples array was empty'

    # form the actual gherkin example text (sans "Examples:", engine adds it)
    text = [u'|' + u'|'.join(step_variables) + u'|']
    for ex in examples:
        # verify the example obj has all the expected headers/fields
        ex_field_diffs = step_variables.difference(ex.keys())
        if ex_field_diffs:
            return None, u'an example object was missing some fields: {} given: {}'.format(ex_field_diffs, ex)

        vals = [unicode(ex[key]) for key in step_variables]
        text.append(u'|' + u'|'.join(vals) + u'|')
    text = u'\n'.join(text)

    log.debug(u'resulting example text\n{}'.format(text))
    return text, None


class TestViewSet(viewsets.ModelViewSet):
    queryset = Test.objects.all()
    serializer_class = TestSerializer

    def update(self, request, pk=None):
        """
        Update the specified test.

        Base code from https://github.com/tomchristie/django-rest-framework/blob/master/rest_framework/mixins.py
        """
        log.debug(u'updating test {} via api'.format(pk))

        test = self.get_object_or_none()
        if test is None:
            return JSONResponse({u'error': u'no test found with id {}'.format(pk)})

        try:
            test_serializer = TestSerializer(test, data=request.DATA)
            if test_serializer.is_valid():
                # save the test
                test_serializer.save()

                # log an entry in the test edit history
                # pull the user out of the data
                user = test_serializer.data[u'user']
                log.debug(u'user {} is updating test {} via api'.format(user, pk))

                log.debug(u'querying test edit history')
                test = Test.objects.get(pk=pk)
                version = test.testedithistory_set.count() + 1

                log.debug(u'saving test {} history version {}'.format(pk, version))
                history_entry = test.testedithistory_set.create(user=user, version=version, steps=test.steps)
                log.debug(u'created test {} history entry {}'.format(pk, history_entry.id))

                return JSONResponse({}, status=200)
            else:
                return JSONResponse(test_serializer.errors, status=400)
        except Exception as e:
            log.error(u'exception when calling delete: {}'.format(unicode(e)))

        return JSONResponse({}, status=400)

    def destroy(self, requset, pk=None):
        """Delete the specified test."""
        try:
            log.debug(u'retrieving test {} to delete it'.format(pk))
            test = Test.objects.get(pk=pk)

            log.debug(u'deleting test {}'.format(pk))
            test.delete()
            log.debug(u'test {} deleted, returning success'.format(pk))

            return JSONResponse({}, status=200)
        except Exception as e:
            log.error(u'exception when calling delete: {}'.format(unicode(e)))

        return JSONResponse({}, status=400)

    @action()
    def start(self, request, pk=None):
        """
        creates a test run to be picked up by the engine.

        also does extra stuff to allow specifying example rows through the run
        api.

        @param request: the http request
        @type request: rest_framework.request.Request
        @param pk: primary key to use to get data
        @return: json response
        """
        log.info(u'starting test run with test {}'.format(pk))

        # get the test
        test = self.get_object_or_none()
        if not test:
            log.error(u'self.get_object() returned None, no test object to start a run with')
            return JSONResponse({u'error': u'unknown test id: {}'.format(pk)}, status=400)

        step_variables = get_step_variables(test.steps)

        # pull the user out of the request data
        user = request.DATA.get(u'user', None)
        if user is None:
            log.error(u'no user specified, returning error')
            return JSONResponse({u'error': u'user not specified'}, status=400)

        # this enables running example-less outlines through the api
        example, error_msg = form_examples(request, step_variables)
        if not example:
            # set up blank text to create the test run with
            example = u''

        if error_msg:
            log.error(error_msg)
            return JSONResponse({u'error': error_msg}, status=400)

        # ensure that if this run is an example-less outline, that we have
        # example text
        if step_variables and not example and not u'Examples:' in test.steps:
            error_msg = u'a test run for a scenario outline was requested without ' \
                        u'an example being provided in the request body or the step text'
            log.error(error_msg)
            return JSONResponse({u'error': error_msg}, status=400)

        # create a test run for the engine package to pick up and run
        # the status being "NEW" will trigger the engine to pick it up
        log.debug(u'creating test run')

        test_run = test.testrun_set.create(user=user, example_text=example)

        log.debug(u'created test run')

        serializer = TestRunSerializer(test_run)
        return JSONResponse(serializer.data, status=200)


class TestRunViewSet(viewsets.ModelViewSet):
    serializer_class = TestRunSerializer

    # if this isn't defined, then a call to the nested router will always
    # return all the entries in the table
    # http://www.django-rest-framework.org/api-guide/filtering.html#filtering-against-the-url
    def get_queryset(self):
        # in the auto url router, the key is labeled test_pk
        # bdd/api/tests/123/runs, 123 -> test_pk
        test_id = self.kwargs[u'test_pk']
        # descend sort the runs, so we can get the latest run id
        return TestRun.objects.filter(test=test_id).order_by(u'-id')


class TestRunStepViewSet(viewsets.ModelViewSet):
    serializer_class = TestRunStepSerializer

    # turn off pagination for steps, if someone is getting step results they probably want them all
    # http://www.django-rest-framework.org/api-guide/pagination
    paginate_by = None

    # if this isn't defined, then a call to the nested router will always
    # return all the entries in the table
    # http://www.django-rest-framework.org/api-guide/filtering.html#filtering-against-the-url
    def get_queryset(self):
        # in the auto url router, the key is labeled run_pk
        # bdd/api/tests/1/runs/123/steps, 123 -> run_pk
        run_id = self.kwargs[u'run_pk']
        return TestRunStep.objects.filter(run=run_id).order_by(u'num')

    def list(self, request, **kwargs):
        """Returns a list of step results for a given test and run id."""
        queryset = self.get_queryset()
        serializer = TestRunStepSerializer(queryset, many=True)
        return JSONResponse({u'steps': serializer.data}, status=200)


class TestRunTable(Table):
    view = TemplateColumn(u'<a href="{% url "bdd-test-run-detail" test_id=record.test_id test_run_id=record.id %}">View</a>', verbose_name=u'View')

    class Meta:
        model = TestRun
        exclude = (u'test', u'example_text', u'text')
        attrs = {u'class': u'table table-striped table-hover'}


class TestForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        """Ensure that steps is in html format."""

        # THE FOLLOWING IS HACKING AROUND TINYMCE's HTML THAT THE STEP FIELD IS EDITED IN
        # we store the steps as plain text in the db, but tinymce's editor displays html
        # so format what we've got in the db with html
        # one of the reasons this is necessary is because Behave wouldn't be able to run against html
        # another is that you would see html returned from the api if we didn't clean this stuff
        if u'instance' in kwargs:
            instance = kwargs[u'instance']

            # convert the steps to html
            instance.steps = steps_to_html(instance.steps)

        super(TestForm, self).__init__(*args, **kwargs)

    # user is set via REMOTE_USER when running in an apollo environment
    user = forms.CharField(widget=forms.TextInput(attrs={u'class': u'form-control'}))
    name = forms.CharField(widget=forms.TextInput(attrs={u'class': u'form-control'}))
    steps = forms.CharField(widget=TinyMCE(attrs={u'class': u'form-control'}))
    tags = TagField(required=False)

    def clean_steps(self):
        # THE FOLLOWING IS HACKING AROUND TINYMCE's HTML THAT THE STEP FIELD IS EDITED IN
        # we strip the steps of html so that we can store plain text in the db
        # Behave will run against this later, so we don't want it formatted in html

        # convert the html to clean plain text
        html_steps = self.data[u'steps']
        cleaned_steps = html_to_steps(html_steps)
        log.debug(u'\nCleaned steps:\n{}'.format(cleaned_steps))
        return cleaned_steps

    class Meta:
        model = Test


class ScenarioOutlineExampleForm(forms.Form):
    """Create a dynamic form comprised of fields generated by the variables in
    a Behave scenario for the user to input. This is necessary because Behave
    Example: entries are cryptic and unfriendly to end-users that simply want
    to use a Scenario Outline as a template for running tests quickly, rather
    than saving their outline in source control with definitive Example entries.
    """

    def __init__(self, *args, **kwargs):
        # create an intermediary dictionary to store the fields in
        # assigning to self.fields before the super() call would be undefined
        dynamic_fields = {}

        # pop all fields with the dynamic field marker in them
        # items creates a view into the dict so we're not in danger of choking on collection modification errors
        for key, value in kwargs.items():
            if DYNAMIC_FIELD_MARKER in key:
                dynamic_fields[key] = value
                kwargs.pop(key)

        super(ScenarioOutlineExampleForm, self).__init__(*args, **kwargs)

        # create dynamic fields
        for key, value in dynamic_fields.iteritems():
            # hash the variable name for use as the control's id
            self.fields[key] = forms.CharField(label=value)

        # create dynamic fields from querydict (request.POST data)
        for arg in args:
            if isinstance(arg, QueryDict):
                for key, value in arg.iteritems():
                    if DYNAMIC_FIELD_MARKER in key:
                        self.fields[key] = forms.CharField(label=value)


def tests(request):
    """Print a list of tests."""
    test_list = Test.objects.all()
    tag_list = Tag.objects.all().order_by(u'name')

    # check if we need to filter the test list based on tags
    # defaults to empty list because we're always passing the list to the template
    tags = request.GET.get(u'tag', [])
    if tags:
        # plus means only those tests that are tagged with every tag
        # TODO: support commas, for aggregating stuff that includes at least one tag in the list
        tags = tags.split(u'+')

        log.debug(u'displaying tests for search tags: {}'.format(tags))

        # order the list by name if search tags are specified
        # this list contains tests if they have any of the tags passed in, so it's still 'unfiltered'
        test_list = test_list.filter(tags__name__in=tags).distinct().order_by(u'name')

        # return only the tests that have every tag specified
        test_list = filter_tags(test_list, tags)
    else:
        # order the list by newest -> oldest if there are no tags specified
        test_list = test_list.order_by(u'-id')

    paginator = Paginator(test_list, 20)  # decides how many results to show per page

    # https://docs.djangoproject.com/en/dev/topics/pagination/
    page = request.GET.get(u'page')
    try:
        tests = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        tests = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        tests = paginator.page(paginator.num_pages)

    return render(request, u'django_bdd/bddscenarios.html', {u'title': u'Scenarios', u'tests': tests, u'tag_list': tag_list, u'searched_tags': tags, u'label_classes': LABEL_CLASSES})


class ResultStep:
    def __init__(self, text, status=u'new', duration=0.0, pair_id=u'', screenshot_url=u''):
        self.text = text
        self.status = status
        self.duration = duration
        self.pair_id = pair_id
        self.screenshot_url = screenshot_url
        self.css_class = StepStatusClasses.get(status, u'')


class ResultScreenshot:
    def __init__(self, url, pair_id=''):
        self.url = url
        self.pair_id = pair_id


def test_runs(request, test_id=None, test_run_id=None):
    log.info(u'show test runs')

    test = None
    test_run = None
    test_run_status = None
    test_steps = None
    queue_position = None  # how many tests are before this one in the queue (string)
    screenshots = []
    step_sets = {}  # dictionary of numbers and lists of steps

    if test_id:
        log.debug(u'test id given: {}'.format(test_id))
        test = Test.objects.get(id=test_id)
        if test_run_id:
            test_run = TestRun.objects.get(id=test_run_id)
        else:
            try:
                test_run = test.testrun_set.latest(u'id')
            except TestRun.DoesNotExist:
                log.error(u'could not find the latest run for test {}'.format(test_id))
                messages.error(request, u'Unable to find latest run for test {}'.format(test_id))
        test_runs = test.testrun_set.all()
    elif test_run_id:
        log.debug(u'test run id given {}'.format(test_run_id))
        test_run = TestRun.objects.get(id=test_run_id)
        test = test_run.test
        test_runs = test.testrun_set.all()
    else:
        # just use all runs if neither id is specified
        test_runs = TestRun.objects.all()

    if test_run:
        log.debug(u'showing test_run with id {}'.format(test_run.id))

        # get the test run status class
        test_run_status = RunStatusClasses.get(test_run.status, u'')

        # get the steps from the db
        try:
            test_steps = TestRunStep.objects.filter(run_id=test_run.id).order_by(u'example_row_num', u'num')
        except TestRunStep.DoesNotExist:
            log.error(u'couldnt find test steps for run: {}'.format(test_run.id))
            messages.error(request, u'Unable to find test steps for test run {}'.format(test_run.id))

        # if the test run status is NEW, run a query to see how many tests are
        # before it in the db
        if test_run.status == NEW:
            def format_number(n):
                """http://stackoverflow.com/a/16671271"""
                return unicode(n)+(u"th" if 4<=n%100<=20 else {1: u"st", 2: u"nd", 3: u"rd"}.get(n%10, u"th"))

            # id__lt is a shortcut for "id < x" (less than)
            # if the status is new or running and the id is less than the run_id being queried
            # it's before us in the queue
            queue_position = len(TestRun.objects.filter(Q(status=NEW) | Q(status=RUNNING), id__lt=test_run.id))

            # say "your test is next in the queue" or "your test is 5th in the queue"
            if queue_position == 0:
                queue_position = u'next'
            else:
                queue_position = format_number(queue_position)

    # match steps with the test run
    if test_run and test_steps:
        # index to find matches between steps and screens
        screen_idx = 1
        for step in test_steps:
            # pair id gives steps and screens a unique id for some fancy ui
            pair_id = None
            screenshot_url = None
            if step.screenshot_s3_key:
                pair_id = screen_idx
                screen_idx += 1

                # we know the s3 key so just form a url out of it
                screenshot_url = s3_util.make_s3_url(step.screenshot_s3_key, extension=u'.png')
                screenshots.append(ResultScreenshot(screenshot_url, pair_id=pair_id))

            if not step.example_row_num in step_sets:
                # create a new list to hold the steps in if it doesn't exist already
                step_sets[step.example_row_num] = []

            # here we're creating the list of steps
            # with the Behave example row number as the key into the dict
            step_sets[step.example_row_num].append(ResultStep(
                step.text,
                status=step.status,
                duration=step.duration,
                pair_id=pair_id,
                screenshot_url=screenshot_url
            ))

    if test_run and test_run.text:
        # break apart the failure text, if it exists, make it readable
        test_run.text = test_run.text.split(u'\n')

    if not test_id and not test_run_id:
        log.debug(u'no test id given, just displaying all runs')

    table = TestRunTable(test_runs)
    table.order_by = u'-id'

    return render(request, u'django_bdd/bddresult.html', {
        u'title': u'Test Runs',
        u'table': table,
        u'test': test,
        u'test_run': test_run,
        u'test_run_status': test_run_status,
        u'screenshots': screenshots,
        u'step_sets': step_sets,
        u'queue_position': queue_position
    })


def test_queue(request):
    log.info('test_queue')

    # grab the user, provided in the REMOTE_USER variable
    current_user = get_user(request)

    # filter the test runs by new/running statuses
    test_runs = TestRun.objects.filter(Q(status=NEW) | Q(status=RUNNING))

    # create the text that summarizes how many tests there are in the queue
    if not test_runs:
        summary_text = u'There are no test runs currently in the queue.'
    elif len(test_runs) == 1:
        summary_text = u'There is one test run in the queue.'
    else:
        summary_text = u'There are {} test runs currently in the queue.'.format(len(test_runs))

    return render(request, u'django_bdd/bddqueue.html', {
        u'summary_text': summary_text,
        u'test_runs': test_runs,
        u'current_user': current_user
    })


def edit_test(request, test_id=None):
    log.info('edit test')

    # grab the user, provided in the REMOTE_USER variable
    user = get_user(request)

    if test_id:
        title = u'Edit Scenario'
        test = get_object_or_404(Test, pk=test_id)
    else:
        title = u'Create Scenario'
        test = Test()

    # update the test's user
    test.user = user

    if request.method == u'POST':
        log.debug(u'{} is saving test {}'.format(user, test))
        form = TestForm(request.POST, instance=test)
        if form.is_valid():
            log.debug(u'saving form')
            form.save()

            log.debug(u'querying test edit history')
            version = test.testedithistory_set.count() + 1

            log.debug(u'saving test {} history version {}'.format(test.id, version))
            history_entry = test.testedithistory_set.create(user=user, version=version, steps=test.steps)
            log.debug(u'created test {} history entry {}'.format(test.id, history_entry.id))

            return redirect(u'bdd-test-list')
    else:
        log.debug(u'{} is viewing test {}'.format(user, test))
        form = TestForm(instance=test)

    # our own steps are already loaded into behave
    steps = runner.get_available_steps()
    steps.sort()

    return render(request, u'django_bdd/bddform.html', {u'title': title, u'form': form, u'steps': steps})


def delete_test(request, test_id=None):
    log.info(u'delete test')

    # build a url to the api call for deleting tests
    url = request.build_absolute_uri(reverse(u'test-detail', args=(test_id,)))

    # use requests to post to the url
    response = requests.delete(url)

    # check the result
    if not response.ok:
        # failed to delete the test
        log.error(u'unable to delete test {}'.format(test_id))
        pass

    return redirect(u'bdd-test-list')


def run_test(request, test_id=None):
    log.info(u'run test')
    test_run_id = None

    # grab the user, provided in the REMOTE_USER variable
    user = get_user(request)

    # build a url to the api call for starting tests
    url = request.build_absolute_uri(reverse(u'test-start', args=(test_id,)))

    # build the request data
    data = {u'user': user}

    log.debug(u'posting to url {} with data {}'.format(url, data))

    # use requests to post to the url
    response = requests.post(url, data=data)

    # check the result
    if response.ok:
        test_run_id = response.json().get(u'id', None)
    else:
        # failed to create a test run
        log.error(u'unable to run test {}'.format(test_id))
        err_msg = unicode(response) + codecs.decode(response.content, 'utf-8', 'ignore')
        log.error(err_msg)
        messages.error(request, u'Failed to create a test run with url {}! Error message: {}'.format(url, err_msg))

    # if a test run was created, direct the user to the url in which the run id is included
    # this is better for copying/pasting result links than just going to the generic results page
    if test_run_id:
        return redirect(u'bdd-test-run-detail', test_id=test_id, test_run_id=test_run_id)
    else:
        return redirect(u'bdd-test-runs', test_id=test_id)


def run_scenario_outline_form_test(request, test_id=None):
    """This view function is used for scenario outlines with variables but no
    Examples: table, using a web form to fill in an example instead of editing
    and saving the test. It's a way to 'templatize' BDD tests for users who want
    to run one-off tests.

    Differs from run_test in that running a test via this method creates a
    test run with example_text populated. It formats the text for that field via
    the POST data from the request with ScenarioOutlineExampleForm.
    """

    log.info('run scenario outline test')

    # don't bother with using the api for this path
    test = Test.objects.get(pk=test_id)
    test_run_id = None

    form = ScenarioOutlineExampleForm(request.POST)
    if form.is_valid():
        # remove the dynamic_ bit of text from the form fields
        # put it all in a fields dict to use for creating the example text
        fields = {}
        for key, value in form.cleaned_data.iteritems():
            fields[key.replace(DYNAMIC_FIELD_MARKER, u'')] = value

        # create the example text from the form fields and values
        # format:
        # | field name | field name |
        # | field value | field value |
        example_text = u'|' + u'|'.join(fields.keys()) + u'|' + u'\n'
        example_text += u'|' + u'|'.join(fields.values()) + u'|'

        if test:
            # create a test run for the engine package to pick up and run
            # the status being "NEW" will trigger the engine to pick it up
            log.debug(u'creating test run')
            test_run = test.testrun_set.create(user=get_user(request), example_text=example_text)
            test_run_id = test_run.id
            log.debug(u'created test run')
        else:
            log.error(u'no test id passed to run_scenario_outline_form_test')
    else:
        log.error(u'form.is_valid() == False, cannot start test')
        messages.error(request, u'Failed to create a test run for test {}, invalid test run values'.format(test_id))

    # if a test run was created, direct the user to the url in which the run id is included
    # this is better for copying/pasting result links than just going to the generic results page
    if test_run_id:
        return redirect(u'bdd-test-run-detail', test_id=test_id, test_run_id=test_run_id)
    else:
        return redirect(u'bdd-test-run', test_id=test_id)

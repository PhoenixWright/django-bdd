from django.conf.urls import patterns, url, include
from rest_framework import routers
from rest_framework_nested import routers as nested_routers
from django_bdd import views

# router docs
# http://www.django-rest-framework.org/api-guide/routers
# https://github.com/alanjds/drf-nested-routers
# router code: https://github.com/tomchristie/django-rest-framework/blob/master/rest_framework/routers.py

# setup and route urls for api calls
# trailing slash removes the requirement of having a trailing slash to api calls
# im just not used to it so imma nuke it
# wrap into a default router to get the root list functionality
api_router_tests = routers.DefaultRouter(trailing_slash=False)
api_router_tests.register(r'tests', views.TestViewSet)

# wire up a nested router to get specific runs of a test and their status
api_router_runs = nested_routers.NestedSimpleRouter(api_router_tests, r'tests', lookup='test', trailing_slash=False)

# since our views have custom queryset getters, the base name needs to be given
# or else django will throw errors, cuz it cant route the request
api_router_runs.register(r'runs', views.TestRunViewSet, base_name='runs')

# wire up a nested router to runs to get the specific steps and their status
api_router_steps = nested_routers.NestedSimpleRouter(api_router_runs, r'runs', lookup='run', trailing_slash=False)

# since our views have custom queryset getters, the base name needs to be given
# or else django will throw errors, cuz it cant route the request
api_router_steps.register(r'steps', views.TestRunStepViewSet, base_name='steps')

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browseable API.
urlpatterns = patterns('',
    # these are for the ui
    url(r'^tests/$', views.tests, name='bdd-test-list'),
    url(r'^tests/new$', views.edit_test, name='bdd-new-test'),
    url(r'^tests/(?P<test_id>\d+)/edit$', views.edit_test, name='bdd-edit-test'),
    url(r'^tests/(?P<test_id>\d+)/start$', views.run_test, name='bdd-run-test'),
    url(r'^tests/(?P<test_id>\d+)/delete$', views.delete_test, name='bdd-delete-test'),

    # url for running a test with dynamic form input
    url(r'^tests/(?P<test_id>\d+)/start-scenario-outline-form-test$', views.run_scenario_outline_form_test, name='bdd-run-scenario-outline-form-test'),

    url(r'^tests/runs$', views.test_runs, name='bdd-all-runs'),
    url(r'^tests/runs/(?P<test_run_id>\d+)$', views.test_runs, name='bdd-test-run'),
    url(r'^tests/(?P<test_id>\d+)/runs$', views.test_runs, name='bdd-test-runs'),
    url(r'^tests/(?P<test_id>\d+)/runs/(?P<test_run_id>\d+)$', views.test_runs, name='bdd-test-run-detail'),

    # url for viewing the test queue
    url(r'^tests/queue$', views.test_queue, name='bdd-test-queue'),

    # ajax calls made by ui
    url(r'^tests/(?P<test_id>\d+)/delete-modal$', views.delete_modal, name='bdd-delete-modal'),
    url(r'^tests/(?P<test_id>\d+)/scenario-outline-example-form$', views.scenario_outline_example_form, name='bdd-scenario-outline-example-form'),

    # for the api
    url(r'^api/', include(api_router_tests.urls)),
    # even though the nested router was init and django should technically
    # know this is a 'subtree' of bdd_api, it dont. so have to add manually
    url(r'^api/', include(api_router_runs.urls)),
    url(r'^api/', include(api_router_steps.urls)),
)

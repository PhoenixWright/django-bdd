from django.conf import settings
from s3util.s3util import S3Util

from django_bdd.models import Test, TestRun, TestRunStep
from rest_framework import serializers


class TestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Test
        fields = ('id', 'user', 'name', 'steps')
        read_only_fields = ('id',)


class TestRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestRun
        fields = ('id', 'example_text', 'status', 'text', 'duration')
        read_only_fields = fields


class TestRunStepSerializer(serializers.ModelSerializer):
    screenshot_url = serializers.SerializerMethodField('get_screenshot_url')

    class Meta:
        model = TestRunStep
        fields = (
            'id',
            'num',
            'example_row_num',
            'text',
            'status',
            'timestamp_start',
            'timestamp_end',
            'duration',
            'screenshot_url'
        )

        # everything in fields except the dynamic screenshot_url field
        read_only_fields = (
            'id',
            'num',
            'example_row_num',
            'text',
            'status',
            'timestamp_start',
            'timestamp_end',
            'duration'
        )

    def get_screenshot_url(self, obj):
        """
        The database stores s3 keys, but any users of the service need those to
        be full urls. Return s3 urls that expire after 365 days.
        """
        s3_util = S3Util(settings.AWS_ACCESS_KEY, settings.AWS_SECRET_ACCESS_KEY, s3_bucket=settings.AWS_BUCKET)

        screenshot_url = ''
        if obj.screenshot_s3_key:
            screenshot_url = s3_util.make_s3_url(obj.screenshot_s3_key)

        return screenshot_url


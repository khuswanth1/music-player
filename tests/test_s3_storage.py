"""S3 backend against moto's in-memory S3 (no network). Verifies the calls, not a real bucket."""

import io

import boto3
from moto import mock_aws

from app.storage.backends import S3Storage


@mock_aws
def test_s3_storage_roundtrip():
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="media")
    storage = S3Storage("media", endpoint_url=None, region="us-east-1", access_key="test", secret_key="test")
    storage.save("audio/a.ogg", io.BytesIO(b"OggS" + b"\0" * 100), "audio/ogg")
    assert storage.exists("audio/a.ogg") and storage.size("audio/a.ogg") == 104
    url = storage.presigned_url("audio/a.ogg", 60)
    assert "media" in url and "audio/a.ogg" in url and "Signature" in url
    storage.delete("audio/a.ogg")
    assert not storage.exists("audio/a.ogg")

"""put / get / delete. Streamed, never read whole into memory."""

from pathlib import Path
from typing import BinaryIO

from botocore.exceptions import ClientError

from mycel.infra.objects.buckets import ensure
from mycel.infra.objects.client import s3

CHUNK = 1024 * 1024


async def put(bucket: str, key: str, body: BinaryIO, content_type: str) -> None:
    await ensure(bucket)
    async with s3() as client:
        await client.upload_fileobj(body, bucket, key, ExtraArgs={"ContentType": content_type})


async def download(bucket: str, key: str, target: Path) -> None:
    """Stream an object to a local file."""
    async with s3() as client:
        response = await client.get_object(Bucket=bucket, Key=key)
        with target.open("wb") as out:
            async for chunk in response["Body"].iter_chunks(CHUNK):
                out.write(chunk)


async def delete(bucket: str, key: str) -> None:
    """Remove an object. A missing object or bucket is already deleted."""
    async with s3() as client:
        try:
            await client.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchBucket":
                raise

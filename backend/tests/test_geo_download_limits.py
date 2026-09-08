import asyncio

import httpx
import pytest
import respx

from app.connectors.geo_ftp import GeoFetchError, GeoFtpClient

URL = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE1nnn/GSE1000/soft/GSE1000_family.soft.gz"


class Chunks(httpx.AsyncByteStream):
    def __init__(self, slow=False):
        self.slow = slow
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for _ in range(20):
            if self.slow:
                await asyncio.sleep(0.02)
            self.read += 1
            yield b"12345"

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_size_limit_stops_before_reading_full_body():
    stream = Chunks()
    with respx.mock as router:
        router.get(URL).mock(return_value=httpx.Response(200, stream=stream))
        with pytest.raises(GeoFetchError, match="上限"):
            await GeoFtpClient().fetch_bytes(URL, max_bytes=10)
    assert stream.read == 3
    assert stream.closed


@pytest.mark.asyncio
async def test_total_timeout_stops_trickling_response():
    stream = Chunks(slow=True)
    with respx.mock as router:
        router.get(URL).mock(return_value=httpx.Response(200, stream=stream))
        with pytest.raises(GeoFetchError, match="超时"):
            await GeoFtpClient(timeout=0.07).fetch_bytes(URL)
    assert stream.read < 20
    assert stream.closed

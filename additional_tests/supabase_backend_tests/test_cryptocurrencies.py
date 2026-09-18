import postgrest
import pytest

from additional_tests.supabase_backend_tests import authenticated_client_1

pytestmark = pytest.mark.asyncio

async def test_paginated_fetch_cryptocurrencies(authenticated_client_1):
    pages = []

    def cryptocurrencies_request_factory(table: postgrest.AsyncRequestBuilder, select_count):
        pages.append(1)
        return (
            table.select(
                "symbol, last_price",
                count=select_count
            )
        )

    raw_currencies = await authenticated_client_1.paginated_fetch(
        authenticated_client_1,
        "cryptocurrencies",
        cryptocurrencies_request_factory
    )
    assert len(raw_currencies) > 1500
    assert 2 <= sum(pages)
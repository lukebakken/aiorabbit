import asyncio
import logging
import os
from unittest import mock
import uuid

from pamqp import commands, constants
from pamqp import exceptions as pamqp_exceptions

import aiorabbit
from aiorabbit import client, exceptions
from tests import testing

LOGGER = logging.getLogger(__name__)


class ContextManagerTestCase(testing.AsyncTestCase):

    @testing.async_test
    async def test_context_manager_open(self):
        async with aiorabbit.connect(
                os.environ['RABBITMQ_URI'], loop=self.loop) as client_:
            await client_.confirm_select()
            self.assertEqual(client_._state,
                             client.STATE_CONFIRM_SELECTOK_RECEIVED)
        self.assertEqual(client_._state, client.STATE_CLOSED)

    @testing.async_test
    async def test_context_manager_exception(self):
        async with aiorabbit.connect(
                os.environ['RABBITMQ_URI'], loop=self.loop) as client_:
            await client_.confirm_select()
            with self.assertRaises(RuntimeError):
                await client_.confirm_select()
        self.assertEqual(client_._state, client.STATE_CLOSED)

    @testing.async_test
    async def test_context_manager_remote_close(self):
        async with aiorabbit.connect(
                os.environ['RABBITMQ_URI'], loop=self.loop) as client_:
            LOGGER.debug('Sending admin shutdown frame')
            client_._on_frame(
                0, commands.Connection.Close(200, 'Admin Shutdown'))
            while not client_.is_closed:
                await asyncio.sleep(0.1)
        self.assertEqual(client_._state, client.STATE_CLOSED)

    @testing.async_test
    async def test_context_manager_already_closed_on_exit(self):
        async with aiorabbit.connect(
                os.environ['RABBITMQ_URI'], loop=self.loop) as client_:
            self.assertFalse(client_.is_closed)
            client_._state = client.STATE_CLOSED
        self.assertTrue(client_.is_closed)
        async with aiorabbit.connect(
                os.environ['RABBITMQ_URI'], loop=self.loop) as client_:
            self.assertFalse(client_.is_closed)
        self.assertTrue(client_.is_closed)


class IntegrationTestCase(testing.ClientTestCase):

    @testing.async_test
    async def test_channel_recycling(self):
        await self.connect()
        self.assertEqual(self.client._channel, 1)
        await self.close()
        await self.connect()
        self.assertEqual(self.client._channel, 1)
        await self.close()

    @testing.async_test
    async def test_double_close(self):
        await self.connect()
        await self.close()
        await self.close()

    @testing.async_test
    async def test_confirm_select(self):
        await self.connect()
        await self.client.confirm_select()
        self.assert_state(client.STATE_CONFIRM_SELECTOK_RECEIVED)
        await self.close()

    @testing.async_test
    async def test_connect_timeout(self):
        with mock.patch.object(self.loop, 'create_connection') as create_conn:
            create_conn.side_effect = asyncio.TimeoutError()
            with self.assertRaises(asyncio.TimeoutError):
                await self.connect()

    @testing.async_test
    async def test_client_close_error(self):
        await self.connect()
        with mock.patch.object(self.client, 'close') as close:
            close.side_effect = RuntimeError('Faux Exception')
            with self.assertRaises(RuntimeError):
                await self.close()

    @testing.async_test
    async def test_update_secret_raises(self):
        await self.connect()
        with self.assertRaises(pamqp_exceptions.AMQPCommandInvalid):
            self.client._write(
                commands.Connection.UpdateSecret('foo', 'bar'))
            await self.client._wait_on_state(
                client.STATE_UPDATE_SECRETOK_RECEIVED)


class PublishingArgumentsTestCase(testing.ClientTestCase):

    @testing.async_test
    async def test_bad_exchange(self):
        await self.connect()
        with self.assertRaises(TypeError):
            await self.client.publish(1, 'foo', b'bar')

    @testing.async_test
    async def test_bad_routing_key(self):
        await self.connect()
        with self.assertRaises(TypeError):
            await self.client.publish('foo', 2, b'bar')

    @testing.async_test
    async def test_bad_message_body(self):
        await self.connect()
        with self.assertRaises(TypeError):
            await self.client.publish('foo', 'bar', {'foo': 'bar'})

    @testing.async_test
    async def test_bad_booleans(self):
        await self.connect()
        for field in ['mandatory', 'immediate']:
            with self.assertRaises(TypeError):
                kwargs = {field: 'qux'}
                await self.client.publish('foo', 'bar', b'baz', **kwargs)

    @testing.async_test
    async def test_bad_strs(self):
        await self.connect()
        for field in ['app_id', 'content_encoding', 'content_type',
                      'correlation_id', 'expiration', 'message_id',
                      'message_type', 'reply_to', 'user_id']:
            with self.assertRaises(TypeError):
                kwargs = {field: 32768}
                await self.client.publish('foo', 'bar', b'baz', **kwargs)

    @testing.async_test
    async def test_bad_ints(self):
        await self.connect()
        for field in ['delivery_mode', 'priority']:
            with self.assertRaises(TypeError):
                kwargs = {field: 'qux'}
                await self.client.publish('foo', 'bar', b'baz', **kwargs)

    @testing.async_test
    async def test_bad_delivery_mode(self):
        await self.connect()
        with self.assertRaises(ValueError):
            await self.client.publish(
                'foo', 'bar', b'baz', delivery_mode=-1)
            await self.client.publish(
                'foo', 'bar', b'baz', delivery_mode=3)

    @testing.async_test
    async def test_bad_headers(self):
        await self.connect()
        with self.assertRaises(TypeError):
            await self.client.publish('foo', 'bar', b'baz', headers=1)

    @testing.async_test
    async def test_bad_priority(self):
        await self.connect()
        with self.assertRaises(ValueError):
            await self.client.publish(
                'foo', 'bar', b'baz', priority=-1)
        with self.assertRaises(ValueError):
            await self.client.publish(
                'foo', 'bar', b'baz', priority=32768)

    @testing.async_test
    async def test_bad_timestamp(self):
        await self.connect()
        with self.assertRaises(TypeError):
            await self.client.publish(
                'foo', 'bar', b'baz', timestamp=1579390178)


class PublishingTestCase(testing.ClientTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.exchange = ''
        self.routing_key = str(uuid.uuid4())
        self.body = bytes(uuid.uuid4().hex, 'latin-1')

    @testing.async_test
    async def test_minimal_publish(self):
        await self.connect()
        await self.client.publish(self.exchange, self.routing_key, self.body)

    @testing.async_test
    async def test_minimal_publish_with_str_body(self):
        await self.connect()
        await self.client.publish(
            self.exchange, self.routing_key, str(self.body))

    @testing.async_test
    async def test_minimal_publish_with_large_body(self):
        body = b'-'.join([uuid.uuid4().bytes
                          for _i in range(0, constants.FRAME_MAX_SIZE)])
        await self.connect()
        await self.client.publish(self.exchange, self.routing_key, body)

    @testing.async_test
    async def test_publish_with_bad_exchange(self):

        def on_channel_close(reply_code, reply_text):
            self.assertEqual(reply_code, 404)
            self.assertTrue(reply_text.startswith('NOT_FOUND - no exchange'))
            self.test_finished.set()

        self.exchange = str(uuid.uuid4())
        self.client.register_channel_close_callback(on_channel_close)
        await self.connect()
        channel = self.client._channel
        await self.client.publish(self.exchange, self.routing_key, self.body)
        await self.test_finished.wait()
        await self.client._wait_on_state(client.STATE_CHANNEL_OPENOK_RECEIVED)

        self.assertEqual(self.client._channel, channel + 1)

    @testing.async_test
    async def test_publish_with_bad_exchange_and_mandatory(self):
        def on_message_return(msg):
            self.assertEqual(msg.exchange, self.exchange)
            self.assertEqual(msg.routing_key, self.routing_key)
            self.assertEqual(msg.body, self.body)
            self.test_finished.set()

        await self.connect()
        self.client.register_message_return_callback(on_message_return)
        await self.client.publish(
            self.exchange, self.routing_key, self.body, mandatory=True)
        await self.test_finished.wait()

    @testing.async_test
    async def test_publish_with_bad_exchange_and_mandatory_no_callback(self):
        await self.connect()
        await self.client.publish(
            self.exchange, self.routing_key, self.body, mandatory=True)
        await self.client._wait_on_state(client.STATE_BASIC_RETURN_RECEIVED)

    @testing.async_test
    async def test_publish_with_confirmation(self):
        await self.connect()
        await self.client.confirm_select()
        result = await self.client.publish(
            self.exchange, self.routing_key, self.body)
        self.assertTrue(result)


class ReconnectPublisherConfirmsTestCase(testing.ClientTestCase):

    @testing.async_test
    async def test_confirm_select_already_invoked_on_reconnect(self):
        await self.connect()
        await self.client.confirm_select()
        self.assertTrue(self.client._publisher_confirms)
        with self.assertRaises(exceptions.CommandInvalid):
            await self.client.exchange_declare(self.uuid4(), self.uuid4())
        self.assertTrue(self.client._publisher_confirms)

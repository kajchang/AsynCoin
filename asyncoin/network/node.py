# -*- coding: utf-8 -*-

from sanic import Sanic, response

import aiohttp
import asyncio
from aioconsole import ainput

from json import loads
import yaml
import logging
import os
from websockets.exceptions import ConnectionClosed
from urllib.parse import urlparse
import socket
import aiosqlite
import sys

from asyncoin.cryptocurrency.blockchain import Blockchain, startup_script, block_template, transaction_template
from asyncoin.cryptocurrency.block import Block
from asyncoin.cryptocurrency.transaction import Transaction
from asyncoin.cryptocurrency.keys import KeyPair

from asyncoin.utilities.encryption import decrypt, encrypt


class Peers:
    """A set of adjacent peers."""

    def __init__(self):
        self.peers = set()
        self.block_subscribers = set()

    async def find_peers(self):
        """Ask all peers for their peers.
        Returns:
            list: a list of the urls of all known peers.
        """
        peers = []

        for peer in self.peers:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://{}/peers'.format(peer)) as response:
                    peers += await response.json()

        return peers

    async def broadcast_transaction(self, transaction):
        """Send all peers a transaction.
        Args:
            transaction (Transaction): transaction to send.
        """
        peers = list(self.peers)
        for peer in peers:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post('http://{}/transaction'.format(peer), data=repr(transaction))

            except aiohttp.client_exceptions.ClientConnectorError:
                self.peers.remove(peer)

    async def broadcast_block(self, block):
        """Send all peers a block.
        Args:
            block (Block): transaction to send.
        """
        peers = list(self.peers)
        for peer in peers:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post('http://{}/block'.format(peer), data=repr(block))

            except aiohttp.client_exceptions.ClientConnectorError:
                self.peers.remove(peer)

        if self.block_subscribers:
            for subsciber in self.block_subscribers:
                try:
                    await subsciber.send(repr(block))

                except ConnectionClosed:
                    self.block_subscribers.remove(subsciber)

    async def find_longest_chain(self):
        """Find the longest chain.
        Returns:
            list: the longest chain of blocks.
        """
        heights = []
        peers = list(self.peers)
        for peer in peers:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('http://{}/height'.format(peer)) as response:
                        height = await response.text()
                        heights.append(int(height))

            except aiohttp.client_exceptions.ClientConnectorError:
                self.peers.remove(peer)

        if heights:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('http://{}/blocks'.format(list(self.peers)[heights.index(max(heights))])) as response:
                        blocks = await response.json()

                return [Block(json_dict=block) for block in blocks]

            except aiohttp.client_exceptions.ClientConnectorError:
                self.peers.remove(peer)

        return []


class Node(Blockchain, Peers):
    """A Node the communicates over Http using Sanic and requests."""

    def __init__(self, port=8000, db='blockchain.db'):
        self.port = port
        self.db = db

        Peers.__init__(self)

        self.app = Sanic(__name__)

        @self.app.route('/block', methods=['POST'])
        async def block(request):
            if request.body is None:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

            try:
                block = Block.from_dict(loads(request.body.decode()))

            except KeyError:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

            if await self.add_block(block):
                await self.broadcast_block(block)

                return response.json({'success': True}, headers={'Access-Control-Allow-Origin': '*'})

            return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/transaction', methods=['POST'])
        async def transaction(request):
            if request.body is None:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

            try:
                transaction = Transaction.from_dict(
                    loads(request.body.decode()))

            except KeyError:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

            if not await self.add_transaction(transaction):
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

            await self.broadcast_transaction(transaction)

            return response.json({'success': True}, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/blocks/<index:number>', methods=['GET'])
        async def blocks(request, index):
            try:
                return response.json(loads(repr(await self.block_from_index(index))), headers={'Access-Control-Allow-Origin': '*'})

            except IndexError:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/getlastblock', methods=['GET'])
        async def getlastblock(request):
            return response.json(loads(repr(await self.last_block())), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/blockrange/<start:number>/<end:number>', methods=['GET'])
        async def blockrange(request, start, end):
            try:
                return response.json(loads(repr(await self.blocks_from_range(start, end))), headers={'Access-Control-Allow-Origin': '*'})

            except IndexError:
                return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/peers', methods=['GET', 'POST'])
        async def peers(request):
            if request.method == 'GET':
                return response.json(list(self.peers), headers={'Access-Control-Allow-Origin': '*'})

            if request.method == 'POST':
                if request.body is None:
                    return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

                if request.body.decode() == '{}:{}'.format(socket.gethostbyname(socket.getfqdn()), self.port):
                    return response.json({'success': False}, headers={'Access-Control-Allow-Origin': '*'})

                self.peers.add(request.body.decode())
                return response.json({'success': True}, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/balance/<address>', methods=['GET'])
        async def balance(request, address):
            return response.text(str(await self.get_balance(address)), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/nonce/<address>', methods=['GET'])
        async def nonce(request, address):
            return response.text(str(await self.get_account_nonce(address)), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/pending', methods=['GET'])
        async def pending(request):
            return response.json(loads(repr(self.pending)), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/config', methods=['GET'])
        async def config(request):
            return response.json(self.config_, headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/difficulty', methods=['GET'])
        def difficulty(request):
            return response.text(str(self.difficulty), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.route('/height', methods=['GET'])
        async def height(request):
            return response.text(str(await self.height()), headers={'Access-Control-Allow-Origin': '*'})

        @self.app.websocket('/subscribeblock')
        async def subscription(request, websocket):
            self.block_subscribers.add(websocket)
            while True:
                try:
                    await websocket.recv()

                except ConnectionClosed:
                    self.block_subscribers.remove(websocket)

    async def mine(self, reward_address, lowest_fee=1):
        """Asynchronous POW task."""
        while True:
            block = await self.mine_block(reward_address, lowest_fee)
            await self.add_block(block)
            await self.broadcast_block(block)

    async def sync(self, uri):
        pass

    async def interface(self):
        """Asynchronous user input task."""
        logging.getLogger('root').setLevel('CRITICAL')
        logging.getLogger('sanic.error').setLevel('CRITICAL')
        logging.getLogger('sanic.access').setLevel('CRITICAL')

        loop = asyncio.get_event_loop()

        while True:
            cmd = await ainput('(NODE) > ')
            cmd = cmd.lower().split()

            if not cmd:
                pass

            elif cmd[0] == 'mine':
                if len(cmd) > 1:
                    if cmd[1] == 'stop':
                        try:
                            mining_task.cancel()
                            del mining_task
                            print('Stopped mining task.')

                        except NameError:
                            print('The node is not mining.')

                    else:
                        if 'mining_task' in locals():
                            print('The node is already mining.')

                        else:
                            mining_task = loop.create_task(self.mine(cmd[1]))
                            print('Started mining task.')

                else:
                    if 'mining_task' in locals():
                        print('The node is already mining.')

                    else:
                        mining_task = loop.create_task(self.mine(self.address))
                        print('Started mining task.')

            elif cmd[0] == 'send':
                with open('./asyncoin/config/keys.yaml') as key_file:
                    enc_private = yaml.load(key_file.read())[
                        'encrypted_private']

                if enc_private:
                    pass_ = await ainput('Enter your Passphrase > ')
                    try:
                        keys = KeyPair(
                            decrypt(pass_.encode(), enc_private).decode())

                    except ValueError:
                        print('Unable to decrypt private key.')
                        continue

                    to = await ainput('Address to send to > ')
                    amount = await ainput('Amount to send > ')

                    try:
                        amount = int(amount)

                    except ValueError:
                        print("That's not a number.")
                        continue

                    fee = await ainput('Fee (at least 1) > ')

                    try:
                        fee = int(fee)

                    except ValueError:
                        print("That's not a number.")
                        continue

                    balance = await self.get_balance(keys.address)

                    if amount > balance:
                        print('You only have {}.'.format(balance))
                        continue

                    transaction = keys.Transaction(
                        to=to, amount=amount, fee=fee, nonce=await self.get_account_nonce(keys.address))

                    print('Created Transaction {}'.format(transaction.hash))

                    await self.add_transaction(transaction)
                    await self.broadcast_transaction(transaction)

                    print('Broadcasting transaction...')

                else:
                    print('No encrypted key found in keys.yaml.')

            elif cmd[0] == 'balance':
                if len(cmd) > 1:
                    print('Balance: {}'.format(await self.get_balance(cmd[1])))

                else:
                    print('Balance: {}'.format(await self.get_balance(self.address)))

            elif cmd[0] == 'exit':
                for task in asyncio.Task.all_tasks():
                    task.cancel()

                loop.stop()

    async def sync(self, sync_url):
        node_url = urlparse(sync_url).netloc if urlparse(
            sync_url).netloc else urlparse(sync_url).path

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get('http://{}/config'.format(node_url)) as response:
                    config = await response.json()

            except aiohttp.client_exceptions.ClientConnectorError:
                print('Unable to sync.')
                sys.exit()

        async with aiosqlite.connect('{}{}'.format(self.port, self.db)) as db:
            await db.executescript(startup_script)
            await db.commit()

        Blockchain.__init__(self, config_=config,
                            db='{}{}'.format(self.port, self.db))

        async with aiohttp.ClientSession() as session:
            async with session.get('http://{}/blocks/0'.format(node_url)) as response:
                block = Block.from_dict(await response.json())

        if self.verify_genesis_block(block):
            async with aiosqlite.connect(self.db) as db:
                await db.execute(block_template, (block.index, block.hash,
                                                  block.nonce, block.previous_hash, block.timestamp))
                await db.execute(transaction_template, (block.hash, block.data[0].hash, block.data[0].to, block.data[0].from_, block.data[
                    0].amount, block.data[0].timestamp, block.data[0].signature, block.data[0].nonce, block.data[0].fee))
                await db.commit()

        while True:
            async with aiohttp.ClientSession() as session:
                async with session.get('http://{}/height'.format(node_url)) as response:
                    height = int(await response.text())

                async with session.get('http://{}/blockrange/0/{}'.format(node_url, height - 1)) as response:
                    await asyncio.gather(*[self.add_block(Block.from_dict(block)) for block in await response.json()])

                if await self.height() == height:
                    break

        self.peers.add(node_url)
        for node in await self.find_peers():
            self.peers.add(node)

        peers = set(self.peers)

        for peer in peers:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post('http://{}/peers'.format(node_url), data='{}:{}'.format(socket.gethostbyname(socket.getfqdn()), self.port))

            except aiohttp.client_exceptions.ClientConnectorError:
                self.peers.remove(peer)

    def run(self, sync=None):
        """Spin up a blockchain and start the Sanic server."""
        with open('./asyncoin/config/keys.yaml') as key_file:
            enc_private = yaml.load(key_file.read())['encrypted_private']

        if enc_private:
            pass_ = input('Enter your Passphrase > ')
            try:
                keys = KeyPair(
                    decrypt(pass_.encode(), enc_private).decode())

            except ValueError:
                raise ValueError('Unable to decrypt private key.')

        else:
            print('No key found in keys.yaml, generating new keys.')
            pass_ = input('Enter a Passphrase > ')
            keys = KeyPair()
            print(
                """
Encrypted Private Key: {0}
Address: {1}
""".format(encrypt(pass_.encode(), keys.hexprivate.encode()), keys.address))

        self.address = keys.address

        if not os.path.exists('{}{}'.format(self.port, self.db)):
            if sync is None:
                Blockchain.__init__(
                    self, genesis_address=keys.address, db='{}{}'.format(self.port, self.db))

                print('Started Blockchain and Mined Genesis Block.')

            else:
                asyncio.get_event_loop().run_until_complete(self.sync(sync))

        else:
            if sync is None:
                Blockchain.__init__(self, db='{}{}'.format(self.port, self.db))

                print('Loaded Blockchain from Database.')

            else:
                os.remove('{}{}'.format(self.port, self.db))
                asyncio.get_event_loop().run_until_complete(self.sync(sync))

        loop = asyncio.get_event_loop()

        self.app.add_task(self.interface())

        loop.create_task(self.app.create_server(
            host=socket.gethostbyname(socket.getfqdn()), port=self.port))

        loop.run_forever()

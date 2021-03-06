import hashlib
import hmac
import logging
import time
from json.decoder import JSONDecodeError
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests
from typing_extensions import Literal

from rotkehlchen.assets.asset import Asset
from rotkehlchen.errors import RemoteError
from rotkehlchen.exchanges.data_structures import Location, Price, Trade, TradePair
from rotkehlchen.exchanges.exchange import ExchangeInterface
from rotkehlchen.inquirer import Inquirer
from rotkehlchen.logging import RotkehlchenLogsAdapter
from rotkehlchen.serialization.deserialize import (
    deserialize_fee,
    deserialize_timestamp_from_date,
    deserialize_trade_type,
)
from rotkehlchen.typing import ApiKey, ApiSecret, AssetAmount, FVal, Timestamp
from rotkehlchen.user_messages import MessagesAggregator
from rotkehlchen.utils.misc import iso8601ts_to_timestamp
from rotkehlchen.utils.serialization import rlk_jsonloads

if TYPE_CHECKING:
    from rotkehlchen.db.dbhandler import DBHandler

logger = logging.getLogger(__name__)
log = RotkehlchenLogsAdapter(logger)

# This corresponds to md5('') and is used in signature generation
MD5_EMPTY_STR = 'd41d8cd98f00b204e9800998ecf8427e'

# Pairs can be found in Basic API doc: https://www.bitcoin.de/de/api/marketplace
BITCOINDE_TRADING_PAIRS = (
    'btceur',
    'bcheur',
    'btgeur',
    'etheur',
    'bsveur',
    'ltceur',
)


def bitcoinde_asset(asset: str) -> Asset:
    return Asset(asset.upper())


def bitcoinde_pair_to_world(pair: str) -> Tuple[Asset, Asset]:
    tx_asset = bitcoinde_asset(pair[:3])
    native_asset = bitcoinde_asset(pair[3:])
    return tx_asset, native_asset


def trade_from_bitcoinde(raw_trade: Dict) -> Trade:

    try:
        timestamp = deserialize_timestamp_from_date(
            raw_trade['successfully_finished_at'],
            'iso8601',
            'bitcoinde',
        )
    except KeyError:
        # For very old trades (2013) bitcoin.de does not return 'successfully_finished_at'
        timestamp = deserialize_timestamp_from_date(
            raw_trade['trade_marked_as_paid_at'],
            'iso8601',
            'bitcoinde',
        )

    trade_type = deserialize_trade_type(raw_trade['type'])
    tx_amount = AssetAmount(FVal(raw_trade['amount_currency_to_trade']))
    native_amount = FVal(raw_trade['volume_currency_to_pay'])
    tx_asset, native_asset = bitcoinde_pair_to_world(raw_trade['trading_pair'])
    pair = TradePair(f'{tx_asset.identifier}_{native_asset.identifier}')
    amount = tx_amount
    rate = Price(native_amount / tx_amount)
    fee_amount = deserialize_fee(raw_trade['fee_currency_to_pay'])
    fee_asset = Asset('EUR')

    return Trade(
        timestamp=timestamp,
        location=Location.BITCOINDE,
        pair=pair,
        trade_type=trade_type,
        amount=amount,
        rate=rate,
        fee=fee_amount,
        fee_currency=fee_asset,
        link=str(raw_trade['trade_id']),
    )


class Bitcoinde(ExchangeInterface):
    def __init__(
            self,
            api_key: ApiKey,
            secret: ApiSecret,
            database: 'DBHandler',
            msg_aggregator: MessagesAggregator,
    ):
        super().__init__('bitcoinde', api_key, secret, database)
        self.uri = 'https://api.bitcoin.de'
        self.session.headers.update({'x-api-key': api_key})
        self.msg_aggregator = msg_aggregator

    def _generate_signature(self, request_type: str, url: str, nonce: str) -> str:
        signed_data = '#'.join([request_type, url, self.api_key, nonce, MD5_EMPTY_STR]).encode()
        signature = hmac.new(
            self.secret,
            signed_data,
            hashlib.sha256,
        ).hexdigest()
        self.session.headers.update({
            'x-api-signature': signature,
        })
        return signature

    def _api_query(
            self,
            verb: Literal['get', 'post'],
            path: str,
            options: Optional[Dict] = None,
    ) -> Dict:
        """
        Queries Bitcoin.de with the given verb for the given path and options
        """
        assert verb in ('get', 'post'), (
            'Given verb {} is not a valid HTTP verb'.format(verb)
        )

        request_path_no_args = '/v4/' + path

        data = ''
        if not options:
            request_path = request_path_no_args
        else:
            request_path = request_path_no_args + '?' + urlencode(options)

        nonce = str(int(time.time() * 1000))
        request_url = self.uri + request_path

        self._generate_signature(
            request_type=verb.upper(),
            url=request_url,
            nonce=nonce,
        )

        headers = {
            'x-api-nonce': nonce,
        }
        if data != '':
            headers.update({
                'Content-Type': 'application/json',
                'Content-Length': str(len(data)),
            })

        log.debug('Bitcoin.de API Query', verb=verb, request_url=request_url)

        try:
            response = getattr(self.session, verb)(request_url, data=data, headers=headers)
        except requests.exceptions.RequestException as e:
            raise RemoteError(f'Bitcoin.de API request failed due to {str(e)}') from e

        try:
            json_ret = rlk_jsonloads(response.text)
        except JSONDecodeError as exc:
            raise RemoteError('Bitcoin.de returned invalid JSON response') from exc

        if response.status_code not in (200, 401):
            if isinstance(json_ret, dict) and 'errors' in json_ret:
                for error in json_ret['errors']:
                    if error.get('field') == 'X-API-KEY' and error.get('code') == 1:
                        raise RemoteError('Provided API Key is in invalid Format')

                    if error.get('code') == 3:
                        raise RemoteError('Provided API Key is invalid')

                raise RemoteError(json_ret['errors'])

            raise RemoteError(
                'Bitcoin.de api request for {} failed with HTTP status code {}'.format(
                    response.url,
                    response.status_code,
                ),
            )

        if not isinstance(json_ret, dict):
            raise RemoteError('Bitcoin.de returned invalid non-dict response')

        return json_ret

    def validate_api_key(self) -> Tuple[bool, str]:
        """
        Validates that the Bitcoin.de API key is good for usage in Rotki
        """

        try:
            self._api_query('get', 'account')
            return True, ""

        except RemoteError as e:
            return False, str(e)

    def query_balances(self, **kwargs: Any) -> Tuple[Optional[Dict[Asset, Dict[str, Any]]], str]:
        balances = {}
        try:
            resp_info = self._api_query('get', 'account')
        except RemoteError as e:
            msg = (
                'Bitcoin.de request failed. Could not reach bitcoin.de due '
                'to {}'.format(e)
            )
            log.error(msg)
            return None, msg

        for currency, balance in resp_info['data']['balances'].items():
            asset = bitcoinde_asset(currency)
            try:
                usd_price = Inquirer().find_usd_price(asset=asset)
            except RemoteError as e:
                self.msg_aggregator.add_error(
                    f'Error processing Bitcoin.de balance entry due to inability to '
                    f'query USD price: {str(e)}. Skipping balance entry',
                )
                continue

            balances[asset] = {
                'amount': balance['total_amount'],
                'usd_value': balance['total_amount'] * usd_price,
            }

        return balances, ''

    def query_online_trade_history(
            self,
            start_ts: Timestamp,
            end_ts: Timestamp,
    ) -> List[Trade]:

        page = 1
        resp_trades = []

        while True:
            resp = self._api_query('get', 'trades', {'state': 1, 'page': page})
            resp_trades.extend(resp['trades'])

            if 'page' not in resp:
                break

            if resp['page']['current'] >= resp['page']['last']:
                break

            page = resp['page']['current'] + 1

        log.debug('Bitcoin.de trade history query', results_num=len(resp_trades))

        trades = []
        for tx in resp_trades:
            try:
                timestamp = iso8601ts_to_timestamp(tx['successfully_finished_at'])
            except KeyError:
                # For very old trades (2013) bitcoin.de does not return 'successfully_finished_at'
                timestamp = iso8601ts_to_timestamp(tx['trade_marked_as_paid_at'])

            if tx['state'] != 1:
                continue
            if timestamp < start_ts or timestamp > end_ts:
                continue
            trades.append(trade_from_bitcoinde(tx))

        return trades

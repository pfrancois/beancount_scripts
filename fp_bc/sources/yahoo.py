
import datetime
from beancount.prices import source as bean_source

import requests
from beancount.core.number import D
import logging

import sys
debug = False


class YahooError(ValueError):
    "An error from the Yahoo API."


class Source(bean_source.Source):
    def get_latest_price(self, ticker):
        log = logging.getLogger()
        log.info(f"yahoo:{ticker}")
        response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", headers={'User-Agent': None})
        try:
            content = next(iter(response.json(parse_float=D).values()))
        except Exception as exc:
            from pprint import pprint
            if debug:
                pprint(exc)
            raise YahooError(f"Invalid response from Yahoo:  {response}")
        if response.status_code != requests.codes.ok:
            raise YahooError(f"Status {response.status_code}: {content['error']}")
        if content['error'] is not None:
            raise YahooError(f"Error fetching Yahoo data: {content['error']}")
        result = content['result'][0]
        try:
            price = D(result["meta"]['regularMarketPrice'])
            timezone = datetime.timezone(
                datetime.timedelta(hours=result["meta"]['gmtoffset'] / 3600000),
                result["meta"]['exchangeTimezoneName'])
            trade_time = datetime.datetime.fromtimestamp(result["meta"]['regularMarketTime'],
                                                         tz=timezone)
        except KeyError:
            raise YahooError(f"Invalid response from Yahoo: {repr(result)}")
        currency = result["meta"]["currency"]
        return bean_source.SourcePrice(price, trade_time, currency)

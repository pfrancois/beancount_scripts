
import datetime
from beancount.prices import source as bean_source

import requests
from beancount.core.number import D
import logging


class YahooError(ValueError):
    "An error from the Yahoo API."


class Source(bean_source.Source):
    def get_latest_price(self, ticker):
        log = logging.getLogger()
        log.info(f"yahoo:{ticker}")
        response = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%s" % ticker)
        content = next(iter(response.json(parse_float=D).values()))
        if response.status_code != requests.codes.ok:
            raise YahooError("Status {}: {}".format(response.status_code, content['error']))
        if content['error'] is not None:
            raise YahooError("Error fetching Yahoo data: {}".format(content['error']))
        result = content['result'][0]
        try:
            price = D(result["meta"]['regularMarketPrice'])
            timezone = datetime.timezone(
                datetime.timedelta(hours=result["meta"]['gmtoffset'] / 3600000),
                result["meta"]['exchangeTimezoneName'])
            trade_time = datetime.datetime.fromtimestamp(result["meta"]['regularMarketTime'],
                                                         tz=timezone)
        except KeyError:
            raise YahooError("Invalid response from Yahoo: {}".format(repr(result)))
        currency = result["meta"]["currency"]
        return bean_source.SourcePrice(price, trade_time, currency)

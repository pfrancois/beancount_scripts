import datetime
from beancount.prices import source as bean_source

import requests
from beancount.core.number import D
import logging
import pytz


class YahooError(ValueError):
    "An error from the Yahoo API."


class Source(bean_source.Source):
    def get_latest_price(self, ticker: str) -> bean_source.SourcePrice:
        try:
            log = logging.getLogger()
            log.info(f"yahoo:{ticker}")
            response = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", headers={'User-Agent': None})
            try:
                content = next(iter(response.json(parse_float=D).values()))
            except Exception as exc:
                log.debug(exc)
                raise YahooError(f"Invalid response from Yahoo:  {response}")
            if response.status_code != requests.codes.ok:
                raise YahooError(f"Status {response.status_code}: {content['error']}")
            if content['error'] is not None:
                raise YahooError(f"Error fetching Yahoo data: {content['error']}")
            result = content['result'][0]
            try:
                price = D(result["meta"]['regularMarketPrice']).quantize(D("0.01"))
                timezone = pytz.timezone(result["meta"]['exchangeTimezoneName'])
                trade_time = timezone.localize(datetime.datetime.fromtimestamp(result["meta"]['currentTradingPeriod']['regular']['end']))
            except KeyError:
                raise YahooError(f"Invalid response from Yahoo: {repr(result)}")
            currency = result["meta"]["currency"]
            log.debug(f"yahoo:{ticker} \t price: {price} \t day:{trade_time} \t cur:{currency}")
            # log.info(f"yahoo:{ticker} \t price: {price} \t day:{trade_time} \t cur:{currency}")
            return bean_source.SourcePrice(price, trade_time, currency)
        except YahooError as e:
            log.error(str(e))
            return None

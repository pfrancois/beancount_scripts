import datetime
import os
from dotenv import load_dotenv
from beancount.prices import source as bean_source
import requests
from beancount.core.number import D
from beancount.core import data
from beancount.core.amount import Amount
import logging
from fp_bc import utils
import pytz


class eodError(ValueError):
    "An error from the eod API."


class Source(bean_source.Source):
    def get_latest_price(self, ticker: str) -> bean_source.SourcePrice:
        log = logging.getLogger()
        log.info(f"eod:{ticker}")
        try:
            load_dotenv("D:/ledger/.env")
            if os.getenv("APIKEY_eob"):
                apikey = os.getenv("APIKEY_eob")
            else:
                raise eodError("pas de config apikey")
            isin = ticker
            baseurl = "https://eodhistoricaldata.com/api/eod"
            params = {"api_token": apikey, "fmt": "json", 'order': "d"}
            url = f"{baseurl}/{isin}.EUFUND"
            r = requests.get(url, params)
            if r.status_code == requests.codes.ok:
                log.debug(f"req {isin} ok")
            else:
                raise eodError(r.status_code, r.reason, url)
            content = r.json(parse_float=D)
            new = content[0]
            price = D(new['close']).quantize(D("0.01"))
            date_naive = utils.strpdate(new['date'])
            timezone = pytz.timezone('Europe/Paris')
            trade_time = timezone.localize(datetime.datetime(date_naive.year, date_naive.month, date_naive.day, 17, 30))
            currency = "EUR"
            log.debug(f"price: {price} \t day:{trade_time} \t cur:{currency}")
            return bean_source.SourcePrice(price, trade_time, currency)
        except eodError as e:
            log.error(str(e))
            return None

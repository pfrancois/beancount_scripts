# -*- coding: utf-8 -*-
""" source pour les sicav amf """

import typing
import datetime
import decimal
import time
import pytz
from beancount.prices import source as bean_source
import bs4  # type: ignore
import logging

import requests
from fp_bc import utils


date_str = typing.Union[datetime.date, str, None]
T = typing.TypeVar("T")
KT = typing.TypeVar("KT")



class AmfException(utils.UtilsException):
    """juste une exception qui gere le format"""

    pass


class FormatException(utils.UtilsException):
    """juste une exception qui gere le format"""

    pass


class Source(bean_source.Source):
    def get_latest_price(self, ticker):
        time.sleep(5)
        payload = {
            "varvalidform": "on",
            "NomProd": "",
            "FAMILLEPROD": "0",
            "selectNRJ": "0",
            "NumAgr": "",
            "CLASSPROD": "0",
            "CodeISIN": ticker,
            "NomSOc": "",
            "action": "new",
            "valid_form": "Lancer+la+recherche",
            "sltix": "1+2+3+INVESTMENT+MANAGERS",
        }
        req = requests.get("https://geco.amf-france.org/Bio/rech_part.aspx", params=payload)
        soup = bs4.BeautifulSoup(req.content, "html.parser")
        values = soup.find_all(class_="ResultatCritereValue")
        keys = soup.find_all(class_="ResultatCritere")
        result = dict(zip([v.get_text() for v in keys], [v.get_text() for v in values]))
        try:
            date_req = utils.strpdate(result["Date VL :"], fmt="%d/%m/%Y")
            dt = datetime.datetime(date_req.year, date_req.month, date_req.day, tzinfo=pytz.utc)
            if (
                result["Valeur (€) :"][-2:] == "00"
                and result["Valeur (€) :"].find(",") != -1
                and len(result["Valeur (€) :"]) > 4
            ):
                result["Valeur (€) :"] = result["Valeur (€) :"][:-2]
            montant_req = utils.to_decimal(s=result["Valeur (€) :"], virgule=True, space=True)
        except Exception:
            raise AmfException("%s inconnu pour l'amf", ticker)
        logging.debug(f"{ticker} => {montant_req}")
        return bean_source.SourcePrice(montant_req, dt, "EUR")
